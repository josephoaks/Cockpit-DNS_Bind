#!/usr/bin/python3
"""
DNS Bind backend for Cockpit
Reads and parses BIND zone files
"""

import json
import sys
import re
import ipaddress
from pathlib import Path
from datetime import datetime

NAMED_CONF = "/etc/named.conf"
NAMED_D_DIR = "/etc/named.d"
ZONES_BASE = "/var/lib/named"


def read_zones():
  """Read all zone definitions from named.conf and named.d"""
  zones = []

  # Read main config
  if Path(NAMED_CONF).exists():
    zones.extend(parse_named_conf(NAMED_CONF))

  # Read named.d includes
  if Path(NAMED_D_DIR).exists():
    for conf_file in Path(NAMED_D_DIR).glob("*.conf"):
      zones.extend(parse_named_conf(str(conf_file)))

  return zones


def create_zone(zone_name, zone_type, primary_ns, contact_email):
  """Create a new DNS zone file with SOA record"""

  # Validate inputs
  if not zone_name or not primary_ns or not contact_email:
    return {"error": "Zone name, primary NS, and contact email are required"}

  # Determine zone file path
  zone_file = f"{ZONES_BASE}/master/{zone_name}"

  # Check if zone file already exists
  if Path(zone_file).exists():
    return {"error": f"Zone file {zone_name} already exists"}

  # Generate initial serial number (YYYYMMDD00 format)
  today = datetime.now().strftime('%Y%m%d')
  serial = int(today + '00')

  # Create zone file content
  zone_content = f"""$TTL 2d
@\t\tIN SOA\t\t{primary_ns}\t{contact_email} (
\t\t\t\t{serial}\t\t; serial
\t\t\t\t3h\t\t; refresh
\t\t\t\t1h\t\t; retry
\t\t\t\t1w\t\t; expiry
\t\t\t\t1d )\t\t; minimum
{zone_name}.\tIN NS\t\t{primary_ns}
"""

  # Ensure master directory exists
  master_dir = Path(f"{ZONES_BASE}/master")
  master_dir.mkdir(parents=True, exist_ok=True)

  # Write zone file
  try:
    with open(zone_file, 'w') as f:
      f.write(zone_content)

    # Set proper permissions
    import os
    os.chmod(zone_file, 0o644)

  except Exception as e:
    return {"error": f"Failed to create zone file: {str(e)}"}

  # Add zone to named.conf
  try:
    zone_definition = f"""
zone "{zone_name}" in {{
\ttype master;
\tfile "master/{zone_name}";
}};
"""
    with open(NAMED_CONF, 'a') as f:
      f.write(zone_definition)
  except Exception as e:
    # Clean up zone file if we can't update named.conf
    Path(zone_file).unlink(missing_ok=True)
    return {"error": f"Failed to update named.conf: {str(e)}"}

  return {
    "success": True,
    "zone": zone_name,
    "file": zone_file,
    "serial": serial
  }


def delete_zone(zone_name):
  """Delete a DNS zone file and remove from named.conf"""
  zones = read_zones()
  zone = next((z for z in zones if z['name'] == zone_name), None)

  if not zone:
    return {"error": f"Zone {zone_name} not found"}

  zone_file = zone.get('file')

  # Delete zone file if it exists
  if zone_file and Path(zone_file).exists():
    try:
      Path(zone_file).unlink()
    except Exception as e:
      return {"error": f"Failed to delete zone file: {str(e)}"}

  # Remove zone from named.conf
  try:
    with open(NAMED_CONF, 'r') as f:
      content = f.read()

    # Remove the zone definition
    zone_pattern = rf'zone\s+"{re.escape(zone_name)}"\s+(?:in\s+)?\{{[^}}]+\}};?\s*'
    content = re.sub(zone_pattern, '', content, flags=re.IGNORECASE | re.DOTALL)

    with open(NAMED_CONF, 'w') as f:
      f.write(content)

  except Exception as e:
    return {"error": f"Failed to update named.conf: {str(e)}"}

  return {"success": True, "zone": zone_name}


def _extract_block(content, start_brace):
  """Given index of an opening brace, return (block_text, index_after_matching_close)."""
  depth = 0
  i = start_brace
  n = len(content)
  while i < n:
    c = content[i]
    if c == '{':
      depth += 1
    elif c == '}':
      depth -= 1
      if depth == 0:
        return content[start_brace + 1:i], i + 1
    i += 1
  return content[start_brace + 1:], n  # unbalanced; best effort


def parse_named_conf(conf_file):
  """Parse named.conf to extract zone definitions (nested-brace safe)."""
  zones = []

  with open(conf_file, 'r') as f:
    content = f.read()

  header = re.compile(r'zone\s+"([^"]+)"\s+(?:in\s+)?\{', re.IGNORECASE)

  for m in header.finditer(content):
    zone_name = m.group(1)
    brace_idx = m.end() - 1
    zone_block, _ = _extract_block(content, brace_idx)

    type_match = re.search(r'type\s+(master|slave|primary|secondary|forward|hint)',
                           zone_block, re.IGNORECASE)
    zone_type = type_match.group(1).capitalize() if type_match else "Primary"
    if zone_type.lower() == "master":
      zone_type = "Primary"
    elif zone_type.lower() == "slave":
      zone_type = "Secondary"
    elif zone_type.lower() == "hint":
      zone_type = "Hint"

    q = chr(34) + chr(39)  # " and '
    file_match = re.search(r'file\s+[' + q + r']?([^' + q + r';\s]+)[' + q + r']?', zone_block)
    zone_file = file_match.group(1) if file_match else None
    if zone_file and not zone_file.startswith('/'):
      zone_file = f"{ZONES_BASE}/{zone_file}"

    zones.append({"name": zone_name, "type": zone_type, "file": zone_file})

  return zones


def parse_soa_record(zone_file):
  """Parse SOA record from zone file"""
  if not zone_file or not Path(zone_file).exists():
    return None

  with open(zone_file, 'r') as f:
    content = f.read()

  # Match SOA record with multiline support
  # Pattern: @ IN SOA primary contact ( serial refresh retry expiry minimum )
  soa_pattern = r'@\s+IN\s+SOA\s+(\S+)\s+(\S+)\s*\(\s*(\d+)\s*;\s*serial\s+(\S+)\s*;\s*refresh\s+(\S+)\s*;\s*retry\s+(\S+)\s*;\s*expiry\s+(\S+)\s*\)\s*;\s*minimum'

  match = re.search(soa_pattern, content, re.MULTILINE | re.DOTALL)

  if match:
    return {
      "primary": match.group(1),
      "contact": match.group(2),
      "serial": int(match.group(3)),
      "refresh": match.group(4),
      "retry": match.group(5),
      "expiry": match.group(6),
      "minimum": match.group(7)
    }

  return None


def parse_ttl(zone_file):
  """Parse $TTL directive from zone file"""
  if not zone_file or not Path(zone_file).exists():
    return None

  with open(zone_file, 'r') as f:
    for line in f:
      match = re.match(r'\$TTL\s+(\S+)', line)
      if match:
        return match.group(1)

  return None



_RR_CLASSES = {"IN", "CH", "HS", "CS"}
_GENERAL_TYPES = {"A", "AAAA", "CNAME", "TXT", "PTR", "SRV", "CAA", "NAPTR", "DNAME", "SPF"}


def _strip_comment(line):
  """Remove a trailing ; comment, honoring double-quoted strings (TXT)."""
  out = []
  in_q = False
  for ch in line:
    if ch == chr(34):
      in_q = not in_q
    if ch == ';' and not in_q:
      break
    out.append(ch)
  return "".join(out)


def _looks_like_ttl(tok):
  return re.fullmatch(r'\d+[smhdwSMHDW]?', tok) is not None


def _logical_records(zone_file):
  """Yield (had_leading_ws, text) per logical RR, joining ()-continuations."""
  with open(zone_file, 'r') as f:
    raw = f.read().splitlines()

  buf, had_ws, depth = "", False, 0
  for line in raw:
    text = _strip_comment(line)
    if depth == 0:
      if text.strip() == "":
        continue
      had_ws = text[:1].isspace()
      buf = text
    else:
      buf += " " + text.strip()
    depth += text.count("(") - text.count(")")
    if depth <= 0:
      depth = 0
      merged = buf.replace("(", " ").replace(")", " ").strip()
      if merged:
        yield had_ws, merged
      buf = ""


def _iter_rrs(zone_file):
  """Yield dicts: name, ttl, rrclass, type, value."""
  if not zone_file or not Path(zone_file).exists():
    return
  last_owner = "@"
  origin = None
  for had_ws, text in _logical_records(zone_file):
    if text.startswith('$'):
      parts = text.split()
      if len(parts) >= 2 and parts[0].upper() == "$ORIGIN":
        origin = parts[1]
      continue
    toks = text.split()
    if not toks:
      continue
    if had_ws:
      owner = last_owner
      idx = 0
    else:
      owner = toks[0]
      idx = 1
    last_owner = owner
    ttl = rrclass = None
    while idx < len(toks):
      t = toks[idx]
      if rrclass is None and t.upper() in _RR_CLASSES:
        rrclass = t.upper(); idx += 1; continue
      if ttl is None and _looks_like_ttl(t):
        ttl = t; idx += 1; continue
      break
    if idx >= len(toks):
      continue
    rtype = toks[idx].upper()
    idx += 1
    value = " ".join(toks[idx:]).strip()
    disp = origin if (owner == "@" and origin) else owner
    yield {"name": disp, "ttl": ttl, "rrclass": rrclass, "type": rtype, "value": value}


def read_zone_records(zone_file):
  """Read general DNS records (A, AAAA, CNAME, TXT, PTR, SRV, ...).
  NS/MX/SOA are handled by their own readers/tabs and excluded here."""
  records = []
  for rr in _iter_rrs(zone_file):
    if rr["type"] in _GENERAL_TYPES:
      records.append({"name": rr["name"], "type": rr["type"], "value": rr["value"]})
  return records


def read_mx_records(zone_file):
  """Read MX records from a zone file (owner-inheritance safe)."""
  mx_records = []
  for rr in _iter_rrs(zone_file):
    if rr["type"] == "MX":
      parts = rr["value"].split()
      if len(parts) >= 2 and parts[0].isdigit():
        mx_records.append({"name": rr["name"],
                           "priority": int(parts[0]),
                           "mailserver": parts[1]})
  return mx_records


def increment_serial(zone_file):
  """Increment the serial number in a zone file"""
  # Read the file
  with open(zone_file, 'r') as f:
    content = f.read()

  # Find the serial line
  serial_pattern = r'(\d{10})\s*;\s*serial'
  match = re.search(serial_pattern, content, re.IGNORECASE)

  if match:
    old_serial = int(match.group(1))
    # Generate new serial: YYYYMMDDNN format
    today = datetime.now().strftime('%Y%m%d')
    today_int = int(today + '00')

    # If serial is from today, increment the last 2 digits
    if old_serial >= today_int and old_serial < today_int + 100:
      new_serial = old_serial + 1
    else:
      # Start fresh for new day
      new_serial = today_int

    # Replace serial in content
    content = re.sub(serial_pattern, f'{new_serial}\t\t; serial', content, flags=re.IGNORECASE)

    # Write back
    with open(zone_file, 'w') as f:
      f.write(content)

    return new_serial

  return None


def update_soa(zone_name, soa_data):
  """Update SOA record in a zone file"""
  zones = read_zones()
  zone = next((z for z in zones if z['name'] == zone_name), None)

  if not zone or not zone.get('file'):
    return {"error": f"Zone {zone_name} not found"}

  zone_file = zone['file']

  # Read the file
  with open(zone_file, 'r') as f:
    content = f.read()

  # Build new SOA record
  new_soa = f'''@\t\tIN SOA\t\t{soa_data['primary']}\t{soa_data['contact']} (
\t\t\t\t{soa_data['serial']}\t\t; serial
\t\t\t\t{soa_data['refresh']}\t\t; refresh
\t\t\t\t{soa_data['retry']}\t\t; retry
\t\t\t\t{soa_data['expiry']}\t\t; expiry
\t\t\t\t{soa_data['minimum']} )\t\t; minimum'''

  # Replace SOA record
  soa_pattern = r'@\s+IN\s+SOA\s+\S+\s+\S+\s*\([^)]+\)\s*;\s*minimum'
  content = re.sub(soa_pattern, new_soa, content, flags=re.MULTILINE | re.DOTALL)

  # Update TTL if provided
  if 'ttl' in soa_data:
    ttl_pattern = r'\$TTL\s+\S+'
    content = re.sub(ttl_pattern, f'$TTL {soa_data["ttl"]}', content)

  # Write back
  with open(zone_file, 'w') as f:
    f.write(content)

  return {"success": True}


def _reverse_fqdn(ip_value):
  """Return the reverse-DNS name for an IP (v4 or v6), or None if not an IP."""
  try:
    return ipaddress.ip_address(ip_value.strip()).reverse_pointer
  except ValueError:
    return None


def _find_reverse_zone(reverse_fqdn, zones):
  """Most-specific hosted in-addr.arpa/ip6.arpa zone that is a suffix of reverse_fqdn."""
  rlabels = reverse_fqdn.lower().split('.')
  best, best_len = None, -1
  for z in zones:
    zname = z.get('name', '').rstrip('.').lower()
    if not (zname.endswith('in-addr.arpa') or zname.endswith('ip6.arpa')):
      continue
    zlabels = zname.split('.')
    if len(zlabels) <= len(rlabels) and rlabels[-len(zlabels):] == zlabels:
      if len(zlabels) > best_len:
        best, best_len = z, len(zlabels)
  return best


def _ptr_owner(reverse_fqdn, zone_name):
  """Label(s) of reverse_fqdn relative to the reverse zone origin (or '@')."""
  rlabels = reverse_fqdn.split('.')
  zlabels = zone_name.rstrip('.').split('.')
  owner = rlabels[:len(rlabels) - len(zlabels)]
  return '.'.join(owner) if owner else '@'


def _fqdn_for(name, zone_name):
  base = zone_name.rstrip('.')
  if name.endswith('.'):
    return name
  if name == '@':
    return base + '.'
  return f"{name}.{base}."


def _create_ptr_record(record_name, ip_value, forward_zone_name, zones):
  """Best-effort PTR creation for an A/AAAA. Never raises; returns a status dict."""
  rev = _reverse_fqdn(ip_value)
  if not rev:
    return {"status": "skipped", "message": f"{ip_value} is not a valid IP address; no PTR created"}
  rzone = _find_reverse_zone(rev, zones)
  if not rzone or not rzone.get('file') or not Path(rzone['file']).exists():
    return {"status": "skipped", "message": f"No hosted reverse zone for {ip_value}; PTR not created"}
  owner = _ptr_owner(rev, rzone['name'])
  target = _fqdn_for(record_name, forward_zone_name)
  for rr in _iter_rrs(rzone['file']):
    if rr['type'] == 'PTR' and rr['name'].rstrip('.').lower() in (owner.lower(), rev.lower()):
      return {"status": "exists",
              "message": f"PTR for {ip_value} already exists ({rr['value']}); left unchanged"}
  with open(rzone['file'], 'a') as f:
    f.write(f"{owner}\tIN PTR\t{target}\n")
  increment_serial(rzone['file'])
  return {"status": "created", "message": f"PTR {owner} -> {target} added to {rzone['name']}"}


def add_record(zone_name, record_name, record_type, record_value, create_ptr=False):
  """Add a DNS record to a zone file"""
  zones = read_zones()
  zone = next((z for z in zones if z['name'] == zone_name), None)

  if not zone or not zone.get('file'):
    return {"error": f"Zone {zone_name} not found"}

  zone_file = zone['file']

  # Check if record already exists
  existing_records = read_zone_records(zone_file)
  if any(r['name'] == record_name for r in existing_records):
    return {"error": f"Record {record_name} already exists"}

  # Add the record
  with open(zone_file, 'a') as f:
    f.write(f"{record_name}\t\tIN {record_type}\t{record_value}\n")

  # Increment serial
  new_serial = increment_serial(zone_file)

  result = {"success": True, "serial": new_serial}
  if create_ptr and record_type in ("A", "AAAA"):
    result["ptr"] = _create_ptr_record(record_name, record_value, zone_name, zones)
  return result


def update_record(zone_name, old_record_name, new_record_name, record_type, record_value):
  """Update a DNS record in a zone file"""
  zones = read_zones()
  zone = next((z for z in zones if z['name'] == zone_name), None)

  if not zone or not zone.get('file'):
    return {"error": f"Zone {zone_name} not found"}

  zone_file = zone['file']

  # Read the file
  with open(zone_file, 'r') as f:
    lines = f.readlines()

  # Find and update the record
  updated = False
  new_lines = []

  for line in lines:
    # Check if this line contains the old record
    if re.match(rf'^{re.escape(old_record_name)}\s+IN\s+A\s+', line):
      # Replace with new record
      new_lines.append(f"{new_record_name}\t\tIN {record_type}\t{record_value}\n")
      updated = True
    else:
      new_lines.append(line)

  if not updated:
    return {"error": f"Record {old_record_name} not found"}

  # Write back
  with open(zone_file, 'w') as f:
    f.writelines(new_lines)

  # Increment serial
  new_serial = increment_serial(zone_file)

  return {"success": True, "serial": new_serial}


def delete_record(zone_name, record_name):
  """Delete a DNS record from a zone file"""
  zones = read_zones()
  zone = next((z for z in zones if z['name'] == zone_name), None)

  if not zone or not zone.get('file'):
    return {"error": f"Zone {zone_name} not found"}

  zone_file = zone['file']

  # Read the file
  with open(zone_file, 'r') as f:
    lines = f.readlines()

  # Filter out the record
  new_lines = []
  deleted = False

  for line in lines:
    # Check if this line contains the record to delete
    if re.match(rf'^{re.escape(record_name)}\s+IN\s+A\s+', line):
      deleted = True
      continue  # Skip this line
    new_lines.append(line)

  if not deleted:
    return {"error": f"Record {record_name} not found"}

  # Write back
  with open(zone_file, 'w') as f:
    f.writelines(new_lines)

  # Increment serial
  new_serial = increment_serial(zone_file)

  return {"success": True, "serial": new_serial}


def add_mx_record(zone_name, record_name, priority, mailserver):
  """Add an MX record to a zone file"""
  zones = read_zones()
  zone = next((z for z in zones if z['name'] == zone_name), None)

  if not zone or not zone.get('file'):
    return {"error": f"Zone {zone_name} not found"}

  zone_file = zone['file']

  try:
    priority = int(priority)
    if priority < 0 or priority > 65535:
      return {"error": "Priority must be between 0 and 65535"}
  except ValueError:
    return {"error": "Priority must be a number"}

  existing_records = read_mx_records(zone_file)
  if any(r['name'] == record_name and r['mailserver'] == mailserver for r in existing_records):
    return {"error": f"MX record {record_name} -> {mailserver} already exists"}

  with open(zone_file, 'a') as f:
    f.write(f"{record_name}\t\tIN MX\t{priority}\t{mailserver}\n")

  new_serial = increment_serial(zone_file)

  return {"success": True, "serial": new_serial}


def update_mx_record(zone_name, old_name, old_mailserver, new_name, priority, mailserver):
  """Update an MX record in a zone file"""
  zones = read_zones()
  zone = next((z for z in zones if z['name'] == zone_name), None)

  if not zone or not zone.get('file'):
    return {"error": f"Zone {zone_name} not found"}

  zone_file = zone['file']

  try:
    priority = int(priority)
    if priority < 0 or priority > 65535:
      return {"error": "Priority must be between 0 and 65535"}
  except ValueError:
    return {"error": "Priority must be a number"}

  with open(zone_file, 'r') as f:
    lines = f.readlines()

  updated = False
  new_lines = []

  for line in lines:
    match = re.match(rf'^{re.escape(old_name)}\s+IN\s+MX\s+\d+\s+{re.escape(old_mailserver)}', line)
    if match:
      new_lines.append(f"{new_name}\t\tIN MX\t{priority}\t{mailserver}\n")
      updated = True
    else:
      new_lines.append(line)

  if not updated:
    return {"error": f"MX record {old_name} -> {old_mailserver} not found"}

  with open(zone_file, 'w') as f:
    f.writelines(new_lines)

  new_serial = increment_serial(zone_file)

  return {"success": True, "serial": new_serial}


def delete_mx_record(zone_name, record_name, mailserver):
  """Delete an MX record from a zone file"""
  zones = read_zones()
  zone = next((z for z in zones if z['name'] == zone_name), None)

  if not zone or not zone.get('file'):
    return {"error": f"Zone {zone_name} not found"}

  zone_file = zone['file']

  with open(zone_file, 'r') as f:
    lines = f.readlines()

  new_lines = []
  deleted = False

  for line in lines:
    match = re.match(rf'^{re.escape(record_name)}\s+IN\s+MX\s+\d+\s+{re.escape(mailserver)}', line)
    if match:
      deleted = True
      continue
    new_lines.append(line)

  if not deleted:
    return {"error": f"MX record {record_name} -> {mailserver} not found"}

  with open(zone_file, 'w') as f:
    f.writelines(new_lines)

  new_serial = increment_serial(zone_file)

  return {"success": True, "serial": new_serial}


def list_zones():
  """List all zones with basic info"""
  zones = read_zones()
  return json.dumps(zones, indent=2)


def get_zone_details(zone_name):
  """Get detailed info about a specific zone including records"""
  zones = read_zones()

  for zone in zones:
    if zone["name"] == zone_name:
      zone["records"] = read_zone_records(zone.get("file"))
      zone["mx_records"] = read_mx_records(zone.get("file"))
      zone["ns_records"] = read_ns_records(zone.get("file"))
      zone["soa"] = parse_soa_record(zone.get("file"))
      zone["ttl"] = parse_ttl(zone.get("file"))
      return json.dumps(zone, indent=2)

  return json.dumps({"error": f"Zone {zone_name} not found"})


def read_zone_options(zone_name):
  """Read zone options from named.conf"""
  zones = read_zones()
  zone = next((z for z in zones if z['name'] == zone_name), None)
  
  if not zone:
    return {"error": f"Zone {zone_name} not found"}
  
  # Find the zone block in named.conf
  if Path(NAMED_CONF).exists():
    with open(NAMED_CONF, 'r') as f:
      content = f.read()
    
    # Find zone block
    zone_pattern = rf'zone\s+"{re.escape(zone_name)}"\s+(?:in\s+)?\{{([^}}]+)\}}'
    match = re.search(zone_pattern, content, re.IGNORECASE | re.DOTALL)
    
    if match:
      zone_block = match.group(1)
      
      options = {
        "allowDynamicUpdates": False,
        "tsigKey": "",
        "enableZoneTransport": False,
        "acls": []
      }
      
      # Check for allow-update
      update_match = re.search(r'allow-update\s*\{\s*key\s+"([^"]+)"', zone_block)
      if update_match:
        options["allowDynamicUpdates"] = True
        options["tsigKey"] = update_match.group(1)
      
      # Check for allow-transfer
      transfer_match = re.search(r'allow-transfer\s*\{([^}]+)\}', zone_block)
      if transfer_match:
        options["enableZoneTransport"] = True
        transfer_content = transfer_match.group(1)
        
        # Parse ACLs
        if 'any' in transfer_content:
          options["acls"].append("any")
        if 'localhost' in transfer_content:
          options["acls"].append("localhost")
        if 'localnets' in transfer_content:
          options["acls"].append("localnets")
      
      return options
  
  return {
    "allowDynamicUpdates": False,
    "tsigKey": "",
    "enableZoneTransport": False,
    "acls": []
  }


def update_zone_options(zone_name, options):
  """Update zone options in named.conf"""
  if not Path(NAMED_CONF).exists():
    return {"error": "named.conf not found"}
  
  with open(NAMED_CONF, 'r') as f:
    content = f.read()
  
  # Find and replace zone block
  zone_pattern = rf'zone\s+"{re.escape(zone_name)}"\s+(?:in\s+)?\{{([^}}]+)\}}'
  match = re.search(zone_pattern, content, re.IGNORECASE | re.DOTALL)
  
  if not match:
    return {"error": f"Zone {zone_name} not found in named.conf"}
  
  old_block = match.group(0)
  zone_content = match.group(1)
  
  # Remove old allow-update and allow-transfer statements
  zone_content = re.sub(r'\s*allow-update\s*\{[^}]+\};?\s*', '\n', zone_content)
  zone_content = re.sub(r'\s*allow-transfer\s*\{[^}]+\};?\s*', '\n', zone_content)
  
  # Add new options
  new_options = []
  
  if options.get('allowDynamicUpdates') and options.get('tsigKey'):
    new_options.append(f'\tallow-update {{ key "{options["tsigKey"]}"; }};')
  
  if options.get('enableZoneTransport'):
    acls = options.get('acls', [])
    if acls:
      acl_list = '; '.join([acl for acl in acls]) + ';'
      new_options.append(f'\tallow-transfer {{ {acl_list} }};')
  
  # Build new zone block
  new_zone_content = zone_content.strip()
  if new_options:
    new_zone_content += '\n' + '\n'.join(new_options) + '\n'
  
  new_block = f'zone "{zone_name}" in {{\n{new_zone_content}\n}}'
  
  # Replace in content
  content = content.replace(old_block, new_block)
  
  # Write back
  with open(NAMED_CONF, 'w') as f:
    f.write(content)
  
  return {"success": True}

def read_ns_records(zone_file):
  """Read NS records from a zone file (owner-inheritance safe)."""
  ns_records = []
  for rr in _iter_rrs(zone_file):
    if rr["type"] == "NS":
      ns_records.append({"name": rr["name"],
                         "nameserver": rr["value"].split()[0] if rr["value"] else ""})
  return ns_records


def add_ns_record(zone_name, record_name, nameserver):
  """Add an NS record to a zone file"""
  zones = read_zones()
  zone = next((z for z in zones if z['name'] == zone_name), None)

  if not zone or not zone.get('file'):
    return {"error": f"Zone {zone_name} not found"}

  zone_file = zone['file']

  existing_records = read_ns_records(zone_file)

  # Check for duplicate
  if any(r['name'] == record_name and r['nameserver'] == nameserver for r in existing_records):
    return {"error": f"NS record for {record_name} pointing to {nameserver} already exists"}

  with open(zone_file, 'a') as f:
    f.write(f"{record_name}\t\tIN NS\t\t{nameserver}\n")

  new_serial = increment_serial(zone_file)

  return {"success": True, "serial": new_serial}


def delete_ns_record(zone_name, record_name, nameserver):
  """Delete an NS record from a zone file"""
  zones = read_zones()
  zone = next((z for z in zones if z['name'] == zone_name), None)

  if not zone or not zone.get('file'):
    return {"error": f"Zone {zone_name} not found"}

  zone_file = zone['file']

  with open(zone_file, 'r') as f:
    lines = f.readlines()

  new_lines = []
  deleted = False

  for line in lines:
    match = re.match(rf'^{re.escape(record_name)}\s+IN\s+NS\s+{re.escape(nameserver)}', line)
    if match:
      deleted = True
      continue
    new_lines.append(line)

  if not deleted:
    return {"error": f"NS record {record_name} -> {nameserver} not found"}

  with open(zone_file, 'w') as f:
    f.writelines(new_lines)

  new_serial = increment_serial(zone_file)

  return {"success": True, "serial": new_serial}


def main():
  if len(sys.argv) < 2:
    print(json.dumps({"error": "No command provided"}))
    sys.exit(1)

  command = sys.argv[1]

  if command == "list":
    print(list_zones())

  elif command == "get" and len(sys.argv) >= 3:
    zone_name = sys.argv[2]
    print(get_zone_details(zone_name))

  elif command == "create-zone" and len(sys.argv) >= 3:
    data = json.loads(sys.argv[2])
    result = create_zone(data['name'], data['type'], data['primary'], data['contact'])
    print(json.dumps(result))

  elif command == "delete-zone" and len(sys.argv) >= 3:
    data = json.loads(sys.argv[2])
    result = delete_zone(data['name'])
    print(json.dumps(result))

  elif command == "add-record" and len(sys.argv) >= 3:
    data = json.loads(sys.argv[2])
    result = add_record(data['zone'], data['name'], data['type'], data['value'],
                        data.get('createReverse', False))
    print(json.dumps(result))

  elif command == "update-record" and len(sys.argv) >= 3:
    data = json.loads(sys.argv[2])
    result = update_record(data['zone'], data['oldName'], data['name'], data['type'], data['value'])
    print(json.dumps(result))

  elif command == "delete-record" and len(sys.argv) >= 3:
    data = json.loads(sys.argv[2])
    result = delete_record(data['zone'], data['name'])
    print(json.dumps(result))

  elif command == "get-zone-options" and len(sys.argv) >= 3:
    zone_name = sys.argv[2]
    options = read_zone_options(zone_name)
    print(json.dumps(options))

  elif command == "update-zone-options" and len(sys.argv) >= 3:
    data = json.loads(sys.argv[2])
    zone_name = data.pop('zone')
    result = update_zone_options(zone_name, data)
    print(json.dumps(result))

  elif command == "add-ns-record" and len(sys.argv) >= 3:
    data = json.loads(sys.argv[2])
    result = add_ns_record(data['zone'], data['name'], data['nameserver'])
    print(json.dumps(result))

  elif command == "delete-ns-record" and len(sys.argv) >= 3:
    data = json.loads(sys.argv[2])
    result = delete_ns_record(data['zone'], data['name'], data['nameserver'])
    print(json.dumps(result))

  elif command == "add-mx-record" and len(sys.argv) >= 3:
    data = json.loads(sys.argv[2])
    result = add_mx_record(data['zone'], data['name'], data['priority'], data['mailserver'])
    print(json.dumps(result))

  elif command == "update-mx-record" and len(sys.argv) >= 3:
    data = json.loads(sys.argv[2])
    result = update_mx_record(data['zone'], data['oldName'], data['oldMailserver'], data['name'], data['priority'], data['mailserver'])
    print(json.dumps(result))

  elif command == "delete-mx-record" and len(sys.argv) >= 3:
    data = json.loads(sys.argv[2])
    result = delete_mx_record(data['zone'], data['name'], data['mailserver'])
    print(json.dumps(result))

  elif command == "update-soa" and len(sys.argv) >= 3:
    data = json.loads(sys.argv[2])
    zone_name = data.pop('zone')
    result = update_soa(zone_name, data)
    print(json.dumps(result))

  else:
    print(json.dumps({"error": f"Unknown command: {command}"}))
    sys.exit(1)


if __name__ == "__main__":
  main()
