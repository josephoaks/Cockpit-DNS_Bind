#!/usr/bin/python3
"""
DNS Bind backend for Cockpit
Reads and parses BIND zone files
"""

import json
import sys
import re
import ipaddress

import bindctl
from pathlib import Path
from datetime import datetime

NAMED_CONF = "/etc/named.conf"
NAMED_D_DIR = "/etc/named.d"
ZONES_BASE = "/var/lib/named"


def _validate_zone_name(zone_name):
  """Reject anything that is not a plain domain name.

  The zone name is used to build the zone file path, so a name containing a
  path separator or .. would write outside the zone directory -- as root. It is
  also the place a network in CIDR notation gets typed by mistake, so that case
  gets a message pointing at the reverse zone helper rather than a stat error.
  """
  n = (zone_name or "").strip()
  if not n:
    return "Zone name is required"
  if re.fullmatch(r'[0-9a-fA-F.:]+/\d{1,3}', n):
    return (f"{n} looks like a network, not a zone name. Use the reverse zone "
            f"helper in the Add Zone dialog to work out the in-addr.arpa or "
            f"ip6.arpa name for it.")
  if len(n) > 253:
    return "Zone name is longer than 253 characters"
  if n in ('.', '..') or n.startswith('.') or '..' in n:
    return f"{n} is not a valid zone name"
  if not re.fullmatch(r'[A-Za-z0-9_*\-.]+\.?', n):
    return (f"{n} is not a valid zone name. Use letters, digits, hyphens and "
            f"dots only.")
  return None


def _qualify(name):
  """Add the trailing dot to a name that is clearly meant to be absolute.

  A name written without a trailing dot is relative to the zone origin, so
  "ns1.pirate.com" in the pirate.com zone becomes ns1.pirate.com.pirate.com --
  which is almost never what someone typing a nameserver or mail host means. A
  single label with no dots ("ns1") is left alone, since that genuinely is a
  relative name.
  """
  n = (name or "").strip()
  if not n or n.endswith('.') or '.' not in n:
    return n
  return n + '.'


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


_ZONE_TYPES = {"primary": "master", "master": "master",
               "secondary": "slave", "slave": "slave",
               "forward": "forward"}


def _validate_addresses(addrs, label):
  """Return (cleaned_list, error). Accepts IPv4/IPv6 literals."""
  cleaned = []
  for a in addrs or []:
    a = a.strip()
    if not a:
      continue
    try:
      ipaddress.ip_address(a)
    except ValueError:
      return None, f"{a} is not a valid IP address for {label}"
    cleaned.append(a)
  if not cleaned:
    return None, f"At least one {label} address is required"
  return cleaned, None


def create_zone(zone_name, zone_type, primary_ns, contact_email,
                primaries=None, forwarders=None):
  """Create a new DNS zone: primary (with zone file), secondary, or forward."""

  if not zone_name:
    return {"error": "Zone name is required"}

  name_err = _validate_zone_name(zone_name)
  if name_err:
    return {"error": name_err}
  zone_name = zone_name.strip()

  btype = _ZONE_TYPES.get((zone_type or "").strip().lower())
  if not btype:
    return {"error": f"Unsupported zone type: {zone_type}"}

  if any(z['name'] == zone_name for z in read_zones()):
    return {"error": f"Zone {zone_name} already exists"}

  # Secondary and forward zones hold no locally authored data: a secondary's
  # contents arrive by transfer, and a forward zone has none at all.
  if btype == "slave":
    addrs, err = _validate_addresses(primaries, "primary server")
    if err:
      return {"error": err}
    zone_body = ("\ttype slave;\n"
                 f"\tfile \"slave/{zone_name}\";\n"
                 "\tprimaries { " + " ".join(f"{a};" for a in addrs) + " };\n")
    Path(f"{ZONES_BASE}/slave").mkdir(parents=True, exist_ok=True)
    return _write_zone_definition(zone_name, zone_body, {"type": "Secondary"})

  if btype == "forward":
    addrs, err = _validate_addresses(forwarders, "forwarder")
    if err:
      return {"error": err}
    zone_body = ("\ttype forward;\n"
                 "\tforward only;\n"
                 "\tforwarders { " + " ".join(f"{a};" for a in addrs) + " };\n")
    return _write_zone_definition(zone_name, zone_body, {"type": "Forward"})

  # Primary
  if not primary_ns or not contact_email:
    return {"error": "Zone name, primary NS, and contact email are required"}

  primary_ns = _qualify(primary_ns)
  contact_email = _qualify(contact_email)

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

  zone_body = ("\ttype master;\n"
               f"\tfile \"master/{zone_name}\";\n")
  result = _write_zone_definition(zone_name, zone_body,
                                  {"type": "Primary", "file": zone_file, "serial": serial})
  if "error" in result:
    # Clean up zone file if we can't update named.conf
    Path(zone_file).unlink(missing_ok=True)
    return result

  # A new zone whose apex NS has no address record will not load. Say so now
  # rather than leaving it to be discovered the next time named restarts.
  ok, msg = bindctl.check_zone(zone_name, zone_file)
  if not ok:
    result["warning"] = (f"The zone was created, but named will not load it yet: {msg}")
  return result


def _write_zone_definition(zone_name, zone_body, extra):
  """Append a zone block to named.conf and return a result dict."""
  backup = bindctl.snapshot(NAMED_CONF)
  try:
    with open(NAMED_CONF, 'a') as f:
      f.write(f"\nzone \"{zone_name}\" in {{\n{zone_body}}};\n")
  except Exception as e:
    return {"error": f"Failed to update named.conf: {str(e)}"}

  err = bindctl.verify_conf_or_restore(backup, NAMED_CONF)
  if err:
    return {"error": err}

  result = {"success": True, "zone": zone_name}
  result.update(extra)
  # A new zone is not picked up by a reload; named.conf has to be reread.
  result["reload"] = bindctl.reconfig()
  return result


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
  conf_backup = bindctl.snapshot(NAMED_CONF)
  try:
    with open(NAMED_CONF, 'r') as f:
      content = f.read()

    # Brace-aware removal: a secondary or forward zone contains nested blocks
    # (primaries { ... };), which a non-greedy [^}]+ match would truncate.
    header = re.compile(rf'\n?zone\s+"{re.escape(zone_name)}"\s+(?:in\s+)?\{{',
                        re.IGNORECASE)
    m = header.search(content)
    if m:
      brace_idx = content.index('{', m.start())
      _, end_idx = _extract_block(content, brace_idx)
      tail = content[end_idx:]
      trailing = len(tail) - len(tail.lstrip(';\n'))
      content = content[:m.start()] + tail[trailing:]

    with open(NAMED_CONF, 'w') as f:
      f.write(content)

  except Exception as e:
    return {"error": f"Failed to update named.conf: {str(e)}"}

  err = bindctl.verify_conf_or_restore(conf_backup, NAMED_CONF)
  if err:
    return {"error": err}

  return {"success": True, "zone": zone_name, "reload": bindctl.reconfig()}


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
  """Yield (had_leading_ws, text, start, end) per logical RR.

  start/end are 0-based inclusive source line indices, so mutators can splice
  the exact lines a record occupies instead of re-matching raw text.
  """
  with open(zone_file, 'r') as f:
    raw = f.read().splitlines()

  buf, had_ws, depth, start = "", False, 0, 0
  for lineno, line in enumerate(raw):
    text = _strip_comment(line)
    if depth == 0:
      if text.strip() == "":
        continue
      had_ws = text[:1].isspace()
      buf = text
      start = lineno
    else:
      buf += " " + text.strip()
    depth += text.count("(") - text.count(")")
    if depth <= 0:
      depth = 0
      merged = buf.replace("(", " ").replace(")", " ").strip()
      if merged:
        yield had_ws, merged, start, lineno
      buf = ""


def _iter_rrs(zone_file):
  """Yield dicts: name, ttl, rrclass, type, value."""
  if not zone_file or not Path(zone_file).exists():
    return
  last_owner = "@"
  origin = None
  for had_ws, text, start, end in _logical_records(zone_file):
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
    yield {"name": disp, "ttl": ttl, "rrclass": rrclass, "type": rtype, "value": value,
           "start": start, "end": end}


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
  soa_data = dict(soa_data)
  soa_data['primary'] = _qualify(soa_data.get('primary', ''))
  soa_data['contact'] = _qualify(soa_data.get('contact', ''))
  zones = read_zones()
  zone = next((z for z in zones if z['name'] == zone_name), None)

  if not zone or not zone.get('file'):
    return {"error": f"Zone {zone_name} not found"}

  zone_file = zone['file']
  guard = bindctl.guard(zone_name, zone_file)

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

  return _commit_zone(guard, {"success": True})


def _commit_zone(guard, result):
  """Validate a modified zone file, roll back if this change broke it, reload.

  Returns either an error dict or the result dict with reload status attached.
  """
  err, warning = bindctl.verify_or_restore(guard)
  if err:
    return {"error": err}
  if warning:
    result["warning"] = warning
  result["reload"] = bindctl.reload_zone(guard["zone"])
  return result


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


def _validate_rdata(record_type, value):
  """Reject rdata that would stop the zone loading. Returns an error or None.

  Only types with an unambiguous shape are checked; anything else is passed
  through so the plugin does not block record types it does not model.
  """
  v = (value or "").strip()
  if not v:
    return "Record value is required"

  if record_type == "A":
    try:
      if not isinstance(ipaddress.ip_address(v), ipaddress.IPv4Address):
        return f"{v} is an IPv6 address; use an AAAA record"
    except ValueError:
      return f"{v} is not a valid IPv4 address"
  elif record_type == "AAAA":
    try:
      if not isinstance(ipaddress.ip_address(v), ipaddress.IPv6Address):
        return f"{v} is an IPv4 address; use an A record"
    except ValueError:
      return f"{v} is not a valid IPv6 address"
  elif record_type in ("CNAME", "PTR", "DNAME"):
    if any(c.isspace() for c in v):
      return f"A {record_type} value must be a single domain name"
    if not re.fullmatch(r'[A-Za-z0-9_*\-./]+', v):
      return f"{v} is not a valid domain name"
  return None


def _fqdn_for(name, zone_name):
  base = zone_name.rstrip('.')
  if name.endswith('.'):
    return name
  if name == '@':
    return base + '.'
  return f"{name}.{base}."


def _norm_name(name, zone_name):
  """Canonical comparison key for an owner name, form-agnostic."""
  return _fqdn_for(name, zone_name).lower()


def _norm_value(value):
  """Canonical comparison key for rdata: collapse whitespace, fold case."""
  return " ".join(value.split()).lower()


def _find_rrs(zone_file, zone_name, name=None, rtype=None, value=None):
  """Parsed RRs matching the given criteria, compared canonically."""
  want_name = _norm_name(name, zone_name) if name is not None else None
  want_type = rtype.upper() if rtype else None
  want_value = _norm_value(value) if value is not None else None

  hits = []
  for rr in _iter_rrs(zone_file):
    if want_name is not None and _norm_name(rr["name"], zone_name) != want_name:
      continue
    if want_type is not None and rr["type"] != want_type:
      continue
    if want_value is not None and _norm_value(rr["value"]) != want_value:
      continue
    hits.append(rr)
  return hits


def _splice_lines(zone_file, spans, replacement=None):
  """Remove the given (start, end) line spans, optionally inserting a
  replacement line at the position of the first span."""
  with open(zone_file, 'r') as f:
    lines = f.readlines()

  drop = set()
  for start, end in spans:
    drop.update(range(start, end + 1))

  first = min(drop)
  out = []
  for i, line in enumerate(lines):
    if i in drop:
      if i == first and replacement is not None:
        out.append(replacement)
      continue
    out.append(line)

  with open(zone_file, 'w') as f:
    f.writelines(out)


def _suggest_reverse_zone(rev):
  """Reverse zone name that would normally hold a PTR for this address.

  Assumes the usual delegation boundary: /24 for IPv4, /64 for IPv6. Anything
  classless (RFC 2317) or otherwise unusual is the admin's call, so this is a
  hint in an error message rather than something acted on automatically.
  """
  labels = rev.split('.')
  if rev.endswith('ip6.arpa'):
    return '.'.join(labels[-(2 + 16):]) if len(labels) > 18 else rev
  return '.'.join(labels[-(2 + 3):]) if len(labels) > 5 else rev


def _create_reverse_zone_for(rev, forward_zone):
  """Create the reverse zone that would hold a PTR for this address.

  The SOA is inherited from the forward zone, so the caller does not have to
  ask for a primary name server and contact that the admin has already given
  once. The boundary is the conventional /24 or /64 -- anything classless is
  the admin's call and is not created automatically.
  """
  needed = _suggest_reverse_zone(rev)
  soa = parse_soa_record(forward_zone.get('file')) if forward_zone else None
  primary = (soa or {}).get('primary')
  contact = (soa or {}).get('contact')
  if not primary or not contact:
    return None, (f"Could not read the SOA of {forward_zone.get('name')} to build "
                  f"{needed}; create the zone manually from the DNS Zones page.")

  result = create_zone(needed, 'Primary', primary, contact)
  if 'error' in result:
    return None, f"Could not create {needed}: {result['error']}"
  return needed, None


def _create_ptr_record(record_name, ip_value, forward_zone_name, zones, force=False,
                       create_zone_if_missing=False):
  """Best-effort PTR creation for an A/AAAA. Never raises; returns a status dict.

  One PTR per address is the recommended practice: a reverse lookup that returns
  several names resolves them in no defined order, which breaks forward-confirmed
  reverse DNS. When the address already has a PTR to a different name we stop and
  report a conflict; the caller decides whether to force a second record.
  """
  rev = _reverse_fqdn(ip_value)
  if not rev:
    return {"status": "skipped", "message": f"{ip_value} is not a valid IP address; no PTR created"}
  rzone = _find_reverse_zone(rev, zones)

  if not rzone or not rzone.get('file') or not Path(rzone['file']).exists():
    needed = _suggest_reverse_zone(rev)
    if not create_zone_if_missing:
      return {"status": "skipped",
              "needed": needed,
              "forward": forward_zone_name,
              "message": (f"No reverse zone hosts {ip_value}, so no PTR was created. "
                          f"The zone that would hold it is {needed}.")}

    forward = next((z for z in zones if z['name'] == forward_zone_name), None)
    created, err = _create_reverse_zone_for(rev, forward)
    if err:
      return {"status": "skipped", "needed": needed, "message": err}
    zones = read_zones()
    rzone = _find_reverse_zone(rev, zones)
    if not rzone or not rzone.get('file'):
      return {"status": "skipped", "needed": needed,
              "message": f"Created {created} but could not find it afterwards"}
    zone_created = created
  else:
    zone_created = None

  owner = rev + '.'
  target = _fqdn_for(record_name, forward_zone_name)
  existing = _find_rrs(rzone['file'], rzone['name'], name=owner, rtype='PTR')

  if existing and not force:
    current = existing[0]['value']
    if _norm_value(current) == _norm_value(target):
      return {"status": "unchanged",
              "message": f"PTR for {ip_value} already points to {target}"}
    return {"status": "conflict",
            "zone": rzone['name'],
            "ip": ip_value,
            "existing": current,
            "target": target,
            "message": (f"{ip_value} already has a PTR record pointing to "
                        f"{current.rstrip('.')}. "
                        f"Adding a second PTR to {target} means reverse lookups for this "
                        f"address return both names in no defined order, which can break "
                        f"mail delivery and other forward-confirmed reverse DNS checks. "
                        f"The usual fix is a CNAME in {forward_zone_name} instead.")}

  guard = bindctl.guard(rzone['name'], rzone['file'])
  with open(rzone['file'], 'a') as f:
    f.write(f"{owner}\tIN PTR\t{target}\n")
  increment_serial(rzone['file'])
  err, warning = bindctl.verify_or_restore(guard)
  if err:
    return {"status": "failed", "message": err}
  msg = f"PTR {owner} -> {target} added to {rzone['name']}"
  if zone_created:
    msg = f"Created reverse zone {zone_created} and added PTR {owner} -> {target}"
  return {"status": "created",
          "message": msg,
          "zoneCreated": zone_created,
          "warning": warning,
          "reload": bindctl.reload_zone(rzone['name'])}


def _delete_ptr_record(record_name, ip_value, forward_zone_name, zones):
  """Remove the PTR for an A/AAAA being deleted, matched on its target name.

  Matching on the target (not just the address) means round-robin and alias A
  records sharing an address only ever drop their own PTR.
  """
  rev = _reverse_fqdn(ip_value)
  if not rev:
    return {"status": "skipped", "message": f"{ip_value} is not a valid IP address"}
  rzone = _find_reverse_zone(rev, zones)
  if not rzone or not rzone.get('file') or not Path(rzone['file']).exists():
    return {"status": "skipped",
            "message": f"No hosted reverse zone for {ip_value} ({_suggest_reverse_zone(rev)}); "
                       f"nothing to remove"}

  target = _fqdn_for(record_name, forward_zone_name)
  hits = _find_rrs(rzone['file'], rzone['name'], name=rev + '.', rtype='PTR', value=target)
  if not hits:
    return {"status": "skipped", "message": f"No PTR for {ip_value} pointing to {target}"}

  guard = bindctl.guard(rzone['name'], rzone['file'])
  _splice_lines(rzone['file'], [(rr['start'], rr['end']) for rr in hits])
  increment_serial(rzone['file'])
  err, warning = bindctl.verify_or_restore(guard)
  if err:
    return {"status": "failed", "message": err}
  return {"status": "deleted",
          "message": f"PTR {rev}. -> {target} removed from {rzone['name']}",
          "warning": warning,
          "reload": bindctl.reload_zone(rzone['name'])}


def add_record(zone_name, record_name, record_type, record_value, create_ptr=False,
               force_ptr=False, create_reverse_zone=False):
  """Add a DNS record to a zone file"""
  zones = read_zones()
  zone = next((z for z in zones if z['name'] == zone_name), None)

  if not zone or not zone.get('file'):
    return {"error": f"Zone {zone_name} not found"}

  zone_file = zone['file']
  guard = bindctl.guard(zone_name, zone_file)

  err = _validate_rdata(record_type, record_value)
  if err:
    return {"error": err}

  # An exact duplicate is an error; the same name may legitimately carry several
  # records (round-robin A, an A alongside a TXT, and so on).
  if _find_rrs(zone_file, zone_name, name=record_name, rtype=record_type, value=record_value):
    return {"error": f"Record {record_name} {record_type} {record_value} already exists"}

  # A name holding a CNAME cannot hold any other data (RFC 1034 3.6.2).
  siblings = _find_rrs(zone_file, zone_name, name=record_name)
  if record_type == 'CNAME' and siblings:
    return {"error": f"{record_name} already has records; a CNAME cannot coexist with other data"}
  if any(rr['type'] == 'CNAME' for rr in siblings):
    return {"error": f"{record_name} is a CNAME; it cannot also hold a {record_type} record"}

  # Add the record
  with open(zone_file, 'a') as f:
    f.write(f"{record_name}\t\tIN {record_type}\t{record_value}\n")

  # Increment serial
  new_serial = increment_serial(zone_file)

  result = _commit_zone(guard, {"success": True, "serial": new_serial})
  if "error" in result:
    return result
  if create_ptr and record_type in ("A", "AAAA"):
    result["ptr"] = _create_ptr_record(record_name, record_value, zone_name, zones,
                                       force=force_ptr,
                                       create_zone_if_missing=create_reverse_zone)
  return result


def add_ptr_for(zone_name, record_name, record_value, force=False, create_reverse_zone=False):
  """Create the PTR for an existing A/AAAA.

  Used both to confirm a forced second PTR and to backfill a record whose
  reverse zone did not exist when it was added.
  """
  zones = read_zones()
  if not any(z['name'] == zone_name for z in zones):
    return {"error": f"Zone {zone_name} not found"}
  return {"success": True,
          "ptr": _create_ptr_record(record_name, record_value, zone_name, zones, force=force,
                                    create_zone_if_missing=create_reverse_zone)}


def update_record(zone_name, old_record_name, new_record_name, record_type, record_value,
                  old_record_value=None):
  """Update a DNS record in a zone file"""
  zones = read_zones()
  zone = next((z for z in zones if z['name'] == zone_name), None)

  if not zone or not zone.get('file'):
    return {"error": f"Zone {zone_name} not found"}

  zone_file = zone['file']
  guard = bindctl.guard(zone_name, zone_file)

  err = _validate_rdata(record_type, record_value)
  if err:
    return {"error": err}

  hits = _find_rrs(zone_file, zone_name, name=old_record_name, rtype=record_type,
                   value=old_record_value)
  if not hits:
    return {"error": f"Record {old_record_name} ({record_type}) not found"}
  if len(hits) > 1:
    return {"error": f"{old_record_name} has {len(hits)} {record_type} records; "
                     f"cannot tell which to update"}

  _splice_lines(zone_file, [(hits[0]['start'], hits[0]['end'])],
                replacement=f"{new_record_name}\t\tIN {record_type}\t{record_value}\n")

  # Increment serial
  new_serial = increment_serial(zone_file)

  return _commit_zone(guard, {"success": True, "serial": new_serial})


def delete_record(zone_name, record_name, record_type=None, record_value=None,
                  delete_ptr=False):
  """Delete a DNS record from a zone file"""
  zones = read_zones()
  zone = next((z for z in zones if z['name'] == zone_name), None)

  if not zone or not zone.get('file'):
    return {"error": f"Zone {zone_name} not found"}

  zone_file = zone['file']
  guard = bindctl.guard(zone_name, zone_file)

  hits = _find_rrs(zone_file, zone_name, name=record_name, rtype=record_type,
                   value=record_value)
  if not hits:
    label = f"{record_name} ({record_type})" if record_type else record_name
    return {"error": f"Record {label} not found"}
  if len(hits) > 1 and record_value is None:
    return {"error": f"{record_name} matches {len(hits)} records; "
                     f"specify the type and value to delete"}

  _splice_lines(zone_file, [(rr['start'], rr['end']) for rr in hits])

  # Increment serial
  new_serial = increment_serial(zone_file)

  result = _commit_zone(guard, {"success": True, "serial": new_serial})
  if "error" in result:
    return result
  if delete_ptr and record_type in ("A", "AAAA") and record_value:
    result["ptr"] = _delete_ptr_record(record_name, record_value, zone_name, zones)
  return result


def add_mx_record(zone_name, record_name, priority, mailserver):
  """Add an MX record to a zone file"""
  mailserver = _qualify(mailserver)
  zones = read_zones()
  zone = next((z for z in zones if z['name'] == zone_name), None)

  if not zone or not zone.get('file'):
    return {"error": f"Zone {zone_name} not found"}

  zone_file = zone['file']
  guard = bindctl.guard(zone_name, zone_file)

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

  return _commit_zone(guard, {"success": True, "serial": new_serial})


def update_mx_record(zone_name, old_name, old_mailserver, new_name, priority, mailserver):
  """Update an MX record in a zone file"""
  mailserver = _qualify(mailserver)
  zones = read_zones()
  zone = next((z for z in zones if z['name'] == zone_name), None)

  if not zone or not zone.get('file'):
    return {"error": f"Zone {zone_name} not found"}

  zone_file = zone['file']
  guard = bindctl.guard(zone_name, zone_file)

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

  return _commit_zone(guard, {"success": True, "serial": new_serial})


def delete_mx_record(zone_name, record_name, mailserver):
  """Delete an MX record from a zone file"""
  mailserver = _qualify(mailserver)
  zones = read_zones()
  zone = next((z for z in zones if z['name'] == zone_name), None)

  if not zone or not zone.get('file'):
    return {"error": f"Zone {zone_name} not found"}

  zone_file = zone['file']
  guard = bindctl.guard(zone_name, zone_file)

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

  return _commit_zone(guard, {"success": True, "serial": new_serial})


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
  """Update zone options in named.conf.

  Rewrites the zone block using brace-aware extraction. The previous regex
  captured up to the first closing brace, so once the block contained a nested
  statement such as allow-transfer { any; }, the next edit truncated the block
  and stranded its tail in the file -- which is how named.conf gets corrupted
  on the second options change rather than the first.
  """
  if not Path(NAMED_CONF).exists():
    return {"error": "named.conf not found"}

  with open(NAMED_CONF, 'r') as f:
    content = f.read()

  header = re.compile(rf'zone\s+"{re.escape(zone_name)}"\s+(?:in\s+)?\{{',
                      re.IGNORECASE)
  m = header.search(content)
  if not m:
    return {"error": f"Zone {zone_name} not found in named.conf"}

  brace_idx = content.index('{', m.start())
  zone_content, end_idx = _extract_block(content, brace_idx)

  # Drop the statements we are about to rewrite, nested braces and all.
  kept = []
  i = 0
  managed = re.compile(r'(allow-update|allow-transfer)\s*\{', re.IGNORECASE)
  while i < len(zone_content):
    hit = managed.search(zone_content, i)
    if not hit:
      kept.append(zone_content[i:])
      break
    kept.append(zone_content[i:hit.start()])
    _, after = _extract_block(zone_content, zone_content.index('{', hit.start()))
    while after < len(zone_content) and zone_content[after] in ';':
      after += 1
    i = after
  zone_content = "".join(kept)

  new_options = []
  if options.get('allowDynamicUpdates') and options.get('tsigKey'):
    new_options.append(f'\tallow-update {{ key "{options["tsigKey"]}"; }};')
  if options.get('enableZoneTransport'):
    acls = options.get('acls', [])
    if acls:
      acl_list = '; '.join([acl for acl in acls]) + ';'
      new_options.append(f'\tallow-transfer {{ {acl_list} }};')

  body = "\n".join(line for line in zone_content.splitlines() if line.strip())
  if new_options:
    body += "\n" + "\n".join(new_options)

  new_block = f'zone "{zone_name}" in {{\n{body}\n}}'
  backup = bindctl.snapshot(NAMED_CONF)
  updated = content[:m.start()] + new_block + content[end_idx:]

  with open(NAMED_CONF, 'w') as f:
    f.write(updated)

  err = bindctl.verify_conf_or_restore(backup, NAMED_CONF)
  if err:
    return {"error": err}

  return {"success": True, "reload": bindctl.reconfig()}


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
  nameserver = _qualify(nameserver)
  zones = read_zones()
  zone = next((z for z in zones if z['name'] == zone_name), None)

  if not zone or not zone.get('file'):
    return {"error": f"Zone {zone_name} not found"}

  zone_file = zone['file']
  guard = bindctl.guard(zone_name, zone_file)

  existing_records = read_ns_records(zone_file)

  # Check for duplicate
  if any(r['name'] == record_name and r['nameserver'] == nameserver for r in existing_records):
    return {"error": f"NS record for {record_name} pointing to {nameserver} already exists"}

  with open(zone_file, 'a') as f:
    f.write(f"{record_name}\t\tIN NS\t\t{nameserver}\n")

  new_serial = increment_serial(zone_file)

  return _commit_zone(guard, {"success": True, "serial": new_serial})


def delete_ns_record(zone_name, record_name, nameserver):
  """Delete an NS record from a zone file"""
  nameserver = _qualify(nameserver)
  zones = read_zones()
  zone = next((z for z in zones if z['name'] == zone_name), None)

  if not zone or not zone.get('file'):
    return {"error": f"Zone {zone_name} not found"}

  zone_file = zone['file']
  guard = bindctl.guard(zone_name, zone_file)

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

  return _commit_zone(guard, {"success": True, "serial": new_serial})


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
    result = create_zone(data['name'], data['type'], data.get('primary'),
                         data.get('contact'), data.get('primaries'),
                         data.get('forwarders'))
    print(json.dumps(result))

  elif command == "delete-zone" and len(sys.argv) >= 3:
    data = json.loads(sys.argv[2])
    result = delete_zone(data['name'])
    print(json.dumps(result))

  elif command == "add-record" and len(sys.argv) >= 3:
    data = json.loads(sys.argv[2])
    result = add_record(data['zone'], data['name'], data['type'], data['value'],
                        data.get('createReverse', False),
                        data.get('forceReverse', False),
                        data.get('createReverseZone', False))
    print(json.dumps(result))

  elif command == "add-ptr" and len(sys.argv) >= 3:
    data = json.loads(sys.argv[2])
    result = add_ptr_for(data['zone'], data['name'], data['value'],
                         data.get('force', False),
                         data.get('createReverseZone', False))
    print(json.dumps(result))

  elif command == "update-record" and len(sys.argv) >= 3:
    data = json.loads(sys.argv[2])
    result = update_record(data['zone'], data['oldName'], data['name'], data['type'],
                           data['value'], data.get('oldValue'))
    print(json.dumps(result))

  elif command == "delete-record" and len(sys.argv) >= 3:
    data = json.loads(sys.argv[2])
    result = delete_record(data['zone'], data['name'], data.get('type'),
                           data.get('value'), data.get('deleteReverse', False))
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
