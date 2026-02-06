#!/usr/bin/python3
"""
ACL Management Backend for DNS/BIND Cockpit Plugin
Handles ACL operations: list, add, update, delete
"""

import sys
import json
import re
from pathlib import Path

# Configuration
NAMED_CONF = "/etc/named.conf"

def read_acls():
  """Read ACL definitions from named.conf"""
  acls = []
  
  if not Path(NAMED_CONF).exists():
    return {"error": "named.conf not found"}
  
  try:
    with open(NAMED_CONF, 'r') as f:
      content = f.read()
    
    # Match ACL definitions: acl "name" { values; };
    acl_pattern = r'acl\s+"([^"]+)"\s*\{([^}]+)\}'
    
    for match in re.finditer(acl_pattern, content, re.IGNORECASE | re.DOTALL):
      acl_name = match.group(1)
      acl_block = match.group(2)
      
      # Extract values (IPs, networks, keywords) - split by semicolon
      values = []
      for line in acl_block.split(';'):
        line = line.strip()
        if line and not line.startswith('#') and not line.startswith('//'):
          values.append(line)
      
      acls.append({
        "name": acl_name,
        "values": values
      })
    
    return {"acls": acls}
    
  except Exception as e:
    return {"error": f"Failed to read ACLs: {str(e)}"}


def add_acl(acl_name, values):
  """Add a new ACL definition to named.conf"""
  if not acl_name or not values:
    return {"error": "ACL name and values are required"}
  
  # Validate ACL name
  if not re.match(r'^[a-zA-Z0-9_\-]+$', acl_name):
    return {"error": "Invalid ACL name. Use only letters, numbers, hyphens, and underscores."}
  
  # Check if ACL already exists
  existing = read_acls()
  if "acls" in existing:
    for acl in existing["acls"]:
      if acl["name"] == acl_name:
        return {"error": f"ACL '{acl_name}' already exists"}
  
  try:
    # Build ACL definition
    acl_def = f'\nacl "{acl_name}" {{\n'
    for value in values:
      acl_def += f'  {value};\n'
    acl_def += '};\n'
    
    # Append to named.conf
    with open(NAMED_CONF, 'a') as f:
      f.write(acl_def)
    
    return {"success": True, "name": acl_name}
    
  except Exception as e:
    return {"error": f"Failed to add ACL: {str(e)}"}


def update_acl(acl_name, values):
  """Update an existing ACL definition"""
  if not acl_name or not values:
    return {"error": "ACL name and values are required"}
  
  try:
    with open(NAMED_CONF, 'r') as f:
      content = f.read()
    
    # Find and replace the ACL block
    acl_pattern = rf'acl\s+"{re.escape(acl_name)}"\s*\{{[^}}]+\}};?\s*'
    match = re.search(acl_pattern, content, re.IGNORECASE | re.DOTALL)
    
    if not match:
      return {"error": f"ACL '{acl_name}' not found"}
    
    old_block = match.group(0)
    
    # Build new ACL definition
    new_block = f'acl "{acl_name}" {{\n'
    for value in values:
      new_block += f'  {value};\n'
    new_block += '};\n'
    
    # Replace in content
    content = content.replace(old_block, new_block)
    
    # Write back
    with open(NAMED_CONF, 'w') as f:
      f.write(content)
    
    return {"success": True, "name": acl_name}
    
  except Exception as e:
    return {"error": f"Failed to update ACL: {str(e)}"}


def delete_acl(acl_name):
  """Delete an ACL definition from named.conf"""
  if not acl_name:
    return {"error": "ACL name is required"}
  
  try:
    with open(NAMED_CONF, 'r') as f:
      content = f.read()
    
    # Remove the ACL block
    acl_pattern = rf'acl\s+"{re.escape(acl_name)}"\s*\{{[^}}]+\}};?\s*'
    content = re.sub(acl_pattern, '', content, flags=re.IGNORECASE | re.DOTALL)
    
    # Write back
    with open(NAMED_CONF, 'w') as f:
      f.write(content)
    
    return {"success": True, "deleted": acl_name}
    
  except Exception as e:
    return {"error": f"Failed to delete ACL: {str(e)}"}


def main():
  if len(sys.argv) < 2:
    print(json.dumps({"error": "No command provided"}))
    sys.exit(1)

  command = sys.argv[1]

  if command == "list":
    result = read_acls()
    print(json.dumps(result))

  elif command == "add" and len(sys.argv) >= 3:
    data = json.loads(sys.argv[2])
    result = add_acl(data['name'], data['values'])
    print(json.dumps(result))

  elif command == "update" and len(sys.argv) >= 3:
    data = json.loads(sys.argv[2])
    result = update_acl(data['name'], data['values'])
    print(json.dumps(result))

  elif command == "delete" and len(sys.argv) >= 3:
    data = json.loads(sys.argv[2])
    result = delete_acl(data['name'])
    print(json.dumps(result))

  else:
    print(json.dumps({"error": f"Unknown command: {command}"}))
    sys.exit(1)


if __name__ == "__main__":
  main()
