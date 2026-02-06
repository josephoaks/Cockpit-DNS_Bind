#!/usr/bin/python3
"""
DNS Forwarders Management Backend for DNS/BIND Cockpit Plugin
Handles forwarder operations: list, add, delete, validate, set policy
"""

import sys
import json
import re
import subprocess
from pathlib import Path

# Configuration
NAMED_CONF = "/etc/named.conf"
NAMED_CONF_OPTIONS = "/etc/named.conf"  # Could be separate file
VALIDATION_FILE = "/var/lib/named/forwarder-validation.json"

def read_validation_data():
  """Read validation data from JSON file"""
  if not Path(VALIDATION_FILE).exists():
    return {}
  
  try:
    with open(VALIDATION_FILE, 'r') as f:
      return json.load(f)
  except:
    return {}

def write_validation_data(data):
  """Write validation data to JSON file"""
  try:
    # Ensure directory exists
    Path(VALIDATION_FILE).parent.mkdir(parents=True, exist_ok=True)
    
    with open(VALIDATION_FILE, 'w') as f:
      json.dump(data, f, indent=2)
    
    return True
  except Exception as e:
    return False

def save_validation_result(ip, supports_dnssec):
  """Save DNSSEC validation result for an IP"""
  data = read_validation_data()
  data[ip] = "yes" if supports_dnssec else "no"
  write_validation_data(data)

def get_validation_result(ip):
  """Get DNSSEC validation result for an IP"""
  data = read_validation_data()
  result = data.get(ip, "yes")  # Default to yes for backward compatibility
  return result == "yes"

def remove_validation_result(ip):
  """Remove validation result for an IP"""
  data = read_validation_data()
  if ip in data:
    del data[ip]
    write_validation_data(data)

def read_forwarders():
  """Read forwarders and policy from named.conf"""
  if not Path(NAMED_CONF).exists():
    return {"error": "named.conf not found"}
  
  try:
    with open(NAMED_CONF, 'r') as f:
      content = f.read()
    
    forwarders = []
    policy = 'automatic'  # default
    
    # Find forwarders block in options section
    # Pattern: forwarders { ip1; ip2; };
    forwarders_match = re.search(r'forwarders\s*\{([^}]+)\}', content, re.DOTALL)
    if forwarders_match:
      forwarder_block = forwarders_match.group(1)
      # Extract IPs
      ips = re.findall(r'(\d+\.\d+\.\d+\.\d+|[0-9a-fA-F:]+)\s*;', forwarder_block)
      for ip in ips:
        forwarders.append({
          "ip": ip,
          "validDns": True,  # Only valid DNS servers are allowed
          "supportsDnssec": get_validation_result(ip)  # Read from validation file
        })
    
    # Find forward policy
    # forward first; or forward only;
    forward_match = re.search(r'forward\s+(first|only)\s*;', content)
    if forward_match:
      forward_type = forward_match.group(1)
      if forward_type == 'first':
        policy = 'automatic'
      elif forward_type == 'only':
        policy = 'enabled'
    elif forwarders_match:
      policy = 'custom'
    else:
      policy = 'disabled'
    
    return {
      "forwarders": forwarders,
      "policy": policy
    }
    
  except Exception as e:
    return {"error": f"Failed to read forwarders: {str(e)}"}


def validate_dns_server(ip):
  """
  Validate that IP is a working DNS server
  Returns: (is_valid_dns, supports_dnssec)
  """
  try:
    # Test basic DNS query
    result = subprocess.run(
      ['dig', '@' + ip, '+short', '+timeout=3', 'google.com', 'A'],
      capture_output=True,
      text=True,
      timeout=5
    )
    
    valid_dns = result.returncode == 0 and result.stdout.strip() != ''
    
    # Test DNSSEC support
    dnssec_result = subprocess.run(
      ['dig', '@' + ip, '+dnssec', '+short', '+timeout=3', 'google.com', 'A'],
      capture_output=True,
      text=True,
      timeout=5
    )
    
    # Check if DNSSEC record (RRSIG) is present
    supports_dnssec = 'RRSIG' in dnssec_result.stdout or dnssec_result.returncode == 0
    
    return (valid_dns, supports_dnssec)
    
  except subprocess.TimeoutExpired:
    return (False, False)
  except Exception as e:
    return (False, False)


def add_forwarder(ip, valid_dns=True, supports_dnssec=True):
  """Add a forwarder to named.conf"""
  try:
    with open(NAMED_CONF, 'r') as f:
      content = f.read()
    
    # Check if forwarders block exists
    forwarders_match = re.search(r'forwarders\s*\{([^}]+)\}', content, re.DOTALL)
    
    if forwarders_match:
      # Add to existing block
      old_block = forwarders_match.group(0)
      forwarder_block = forwarders_match.group(1)
      
      # Add new IP
      new_block = f'forwarders {{\n{forwarder_block.rstrip()}\n\t{ip};\n}}'
      content = content.replace(old_block, new_block)
    else:
      # Create new forwarders block in options section
      options_match = re.search(r'options\s*\{', content)
      if options_match:
        # Insert after options {
        insert_pos = options_match.end()
        new_forwarders = f'\n\tforwarders {{\n\t\t{ip};\n\t}};\n'
        content = content[:insert_pos] + new_forwarders + content[insert_pos:]
      else:
        # Create options block
        content += f'\noptions {{\n\tforwarders {{\n\t\t{ip};\n\t}};\n}};\n'
    
    # Write back
    with open(NAMED_CONF, 'w') as f:
      f.write(content)
    
    # Save DNSSEC validation result
    save_validation_result(ip, supports_dnssec)
    
    return {
      "success": True,
      "ip": ip,
      "validDns": valid_dns,
      "supportsDnssec": supports_dnssec
    }
    
  except Exception as e:
    return {"error": f"Failed to add forwarder: {str(e)}"}


def delete_forwarder(ip):
  """Remove a forwarder from named.conf"""
  try:
    with open(NAMED_CONF, 'r') as f:
      content = f.read()
    
    # Find and update forwarders block
    forwarders_match = re.search(r'forwarders\s*\{([^}]+)\}', content, re.DOTALL)
    if not forwarders_match:
      return {"error": "No forwarders configured"}
    
    old_block = forwarders_match.group(0)
    forwarder_block = forwarders_match.group(1)
    
    # Remove the IP line
    new_block_content = re.sub(rf'\s*{re.escape(ip)}\s*;\s*\n?', '', forwarder_block)
    
    if new_block_content.strip():
      # Still have forwarders
      new_block = f'forwarders {{{new_block_content}}}'
    else:
      # No more forwarders, remove entire block
      new_block = ''
    
    content = content.replace(old_block, new_block)
    
    # Write back
    with open(NAMED_CONF, 'w') as f:
      f.write(content)
    
    # Remove validation result
    remove_validation_result(ip)
    
    return {"success": True, "deleted": ip}
    
  except Exception as e:
    return {"error": f"Failed to delete forwarder: {str(e)}"}


def set_forward_policy(policy):
  """
  Set the forward policy
  Policy options: disabled, automatic, enabled, custom
  """
  try:
    with open(NAMED_CONF, 'r') as f:
      content = f.read()
    
    # Remove existing forward statement
    content = re.sub(r'\s*forward\s+(first|only)\s*;\s*\n?', '', content)
    
    # Add new forward statement based on policy
    if policy == 'disabled':
      # Remove forwarders block entirely
      content = re.sub(r'\s*forwarders\s*\{[^}]+\}\s*;\s*\n?', '', content, flags=re.DOTALL)
    elif policy == 'automatic':
      # forward first;
      options_match = re.search(r'^\s*options\s*\{', content, re.MULTILINE)
      if options_match:
        insert_pos = options_match.end()
        content = content[:insert_pos] + '\n\tforward first;' + content[insert_pos:]
    elif policy == 'enabled':
      # forward only;
      options_match = re.search(r'^\s*options\s*\{', content, re.MULTILINE)
      if options_match:
        insert_pos = options_match.end()
        content = content[:insert_pos] + '\n\tforward only;' + content[insert_pos:]
    elif policy == 'custom':
      # No forward statement, just use forwarders
      pass
    
    # Write back
    with open(NAMED_CONF, 'w') as f:
      f.write(content)
    
    return {"success": True, "policy": policy}
    
  except Exception as e:
    return {"error": f"Failed to set policy: {str(e)}"}


def main():
  if len(sys.argv) < 2:
    print(json.dumps({"error": "No command provided"}))
    sys.exit(1)

  command = sys.argv[1]

  if command == "list":
    result = read_forwarders()
    print(json.dumps(result))

  elif command == "validate" and len(sys.argv) >= 3:
    data = json.loads(sys.argv[2])
    valid_dns, supports_dnssec = validate_dns_server(data['ip'])
    result = {
      "validDns": valid_dns,
      "supportsDnssec": supports_dnssec
    }
    print(json.dumps(result))

  elif command == "add" and len(sys.argv) >= 3:
    data = json.loads(sys.argv[2])
    result = add_forwarder(
      data['ip'],
      data.get('validDns', True),
      data.get('supportsDnssec', True)
    )
    print(json.dumps(result))

  elif command == "delete" and len(sys.argv) >= 3:
    data = json.loads(sys.argv[2])
    result = delete_forwarder(data['ip'])
    print(json.dumps(result))

  elif command == "set-policy" and len(sys.argv) >= 3:
    data = json.loads(sys.argv[2])
    result = set_forward_policy(data['policy'])
    print(json.dumps(result))

  else:
    print(json.dumps({"error": f"Unknown command: {command}"}))
    sys.exit(1)


if __name__ == "__main__":
  main()
