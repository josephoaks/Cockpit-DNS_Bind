#!/usr/bin/python3
"""
DNS Bind backend for Cockpit
Reads and parses BIND zone files
"""

import json
import sys
import re
import ipaddress
import os
import shutil
import tempfile

import bindctl

# dns-bind.py and bindctl.py are installed together and must be updated
# together. A partial deployment otherwise surfaces as an opaque traceback from
# whichever call happens to reach a missing helper first.
for _required in ("guard", "verify_or_restore", "zone_is_dynamic", "freeze_zone",
                  "thaw_zone", "sync_zone", "reload_zone", "reconfig", "snapshot"):
  if not hasattr(bindctl, _required):
    raise SystemExit(json.dumps({
      "error": f"backend/bindctl.py is out of date: it has no {_required}(). "
               f"Reinstall the plugin so both backend files come from the same "
               f"version."}))
from pathlib import Path
from datetime import datetime

NAMED_CONF = "/etc/named.conf"
NAMED_D_DIR = "/etc/named.d"
ZONES_BASE = "/var/lib/named"


def _is_default_zone(name):
  """Zones a stock named.conf ships with, which an import should not bring over.

  Mirrors isDefaultZone() in src/utils/reverseZone.js. The IPv6 test covers both
  loopback forms and is not pinned to an exact nibble count, because SLES
  declares that zone with 31 nibbles rather than 32.
  """
  n = (name or "").strip().rstrip('.').lower()
  if not n or n == '.':
    return True
  if n in ('localhost', 'localhost.localdomain'):
    return True
  if re.search(r'(^|\.)127\.in-addr\.arpa$', n):
    return True
  if n in ('0.in-addr.arpa', '255.in-addr.arpa', '0.ip6.arpa'):
    return True
  if re.fullmatch(r'[01](\.0){27,31}\.ip6\.arpa', n):
    return True
  return False


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
  """Increment the serial in a zone file's SOA record.

  The serial is located through the zone parser rather than by looking for a
  '; serial' comment. Zones this plugin did not write -- hand-maintained ones,
  anything normalized by named-compilezone, output from other tooling -- carry
  no such comment, and keying on it meant their serial silently never moved and
  secondaries stopped seeing updates.
  """
  soa = next((rr for rr in _iter_rrs(zone_file) if rr["type"] == "SOA"), None)
  if not soa:
    return None

  # SOA rdata is: MNAME RNAME serial refresh retry expiry minimum
  parts = soa["value"].split()
  if len(parts) < 3 or not parts[2].isdigit():
    return None
  old_serial = int(parts[2])

  today_int = int(datetime.now().strftime('%Y%m%d') + '00')
  if today_int <= old_serial < today_int + 100:
    new_serial = old_serial + 1
  elif old_serial >= today_int + 100:
    # Already ahead of today; keep moving forward rather than going backwards,
    # since a serial that decreases stops zone transfers.
    new_serial = old_serial + 1
  else:
    new_serial = today_int

  with open(zone_file, 'r') as f:
    lines = f.readlines()

  # Replace the serial in place so the file's formatting is preserved.
  pattern = re.compile(rf'(?<![\d.]){old_serial}(?![\d.])')
  for i in range(soa["start"], min(soa["end"] + 1, len(lines))):
    if pattern.search(lines[i]):
      lines[i] = pattern.sub(str(new_serial), lines[i], count=1)
      break
  else:
    return None

  with open(zone_file, 'w') as f:
    f.writelines(lines)

  return new_serial


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
  # A zone frozen for editing must be thawed on every path out of here,
  # including the failure paths -- leaving it frozen silently stops dynamic
  # updates, so DHCP or AD clients quietly stop registering.
  def finish(payload):
    if guard.get("frozen"):
      ok, msg = bindctl.thaw_zone(guard["zone"])
      if ok:
        # thaw reloads the zone itself, so no separate reload is needed.
        payload.setdefault("reload", {"status": "reloaded", "via": "rndc",
                                      "message": f"rndc thaw {guard['zone']} succeeded"})
      else:
        payload["thawFailed"] = (
          f"{guard['zone']} could not be thawed and is still frozen, so dynamic "
          f"updates to it are being refused. Run: rndc thaw {guard['zone']}. "
          f"{msg}")
    return payload

  if guard.get("freezeError"):
    return finish({"error": f"Could not prepare {guard['zone']} for editing: "
                            f"{guard['freezeError']}"})

  err, warning = bindctl.verify_or_restore(guard)
  if err:
    return finish({"error": err})
  if warning:
    result["warning"] = warning
  if not guard.get("frozen"):
    result["reload"] = bindctl.reload_zone(guard["zone"])
  return finish(result)


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


def _canonical_owner(name, zone_name):
  """Return (fqdn, error) for a record owner name.

  Owner names are written fully qualified. That matches what yast2-dns-server
  wrote, what named-compilezone produces on import, and what the PTR writer
  already does, so a zone file does not end up half one style and half another.

  It also closes a double-suffix trap: a name typed as "www.example.com" without
  the trailing dot is relative by zone file rules and becomes
  www.example.com.example.com. Someone typing the zone into the name field means
  the fully qualified name, so that case is detected rather than obeyed.
  """
  raw = (name or "").strip()
  if not raw:
    return None, "Record name is required"

  base = zone_name.rstrip('.').lower()

  if raw == '@':
    return base + '.', None

  if raw.endswith('.'):
    fqdn = raw
  else:
    lowered = raw.lower()
    if lowered == base or lowered.endswith('.' + base):
      # Fully qualified but missing the trailing dot.
      fqdn = raw + '.'
    else:
      fqdn = f"{raw}.{base}."

  label_part = fqdn[:-1]
  if not re.fullmatch(r'(\*|[A-Za-z0-9_](?:[A-Za-z0-9_-]*[A-Za-z0-9_])?)'
                      r'(\.(\*|[A-Za-z0-9_](?:[A-Za-z0-9_-]*[A-Za-z0-9_])?))*',
                      label_part):
    return None, f"{raw} is not a valid record name"

  if not (fqdn.lower() == base + '.' or fqdn.lower().endswith('.' + base + '.')):
    return None, (f"{fqdn} is not inside {zone_name}. A zone can only hold "
                  f"records for names within it.")

  return fqdn, None


def _qualify_rdata(record_type, value):
  """Add the trailing dot to the domain name inside a record's rdata.

  Which token holds the name depends on the type: SRV puts it fourth after
  priority, weight and port; MX puts it second after the preference. Qualifying
  the whole string happens to work when the name is last, but breaks on a root
  target of "." and would corrupt anything with trailing fields.
  """
  v = (value or "").strip()
  if record_type in ("CNAME", "PTR", "DNAME", "NS"):
    return _qualify(v)
  if record_type == "MX":
    parts = v.split()
    if len(parts) == 2:
      return f"{parts[0]} {_qualify(parts[1])}"
    return v
  if record_type == "SRV":
    parts = v.split()
    if len(parts) == 4 and parts[3] != '.':
      return f"{parts[0]} {parts[1]} {parts[2]} {_qualify(parts[3])}"
    return v
  return v


# Types whose rdata contains a domain name needing the same trailing-dot
# treatment as an owner name.
_NAME_VALUED = ("CNAME", "PTR", "DNAME", "NS", "MX", "SRV")


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
  elif record_type == "SRV":
    # priority weight port target
    parts = v.split()
    if len(parts) != 4:
      return "An SRV value must be: priority weight port target"
    for label, num in zip(("priority", "weight", "port"), parts[:3]):
      if not num.isdigit() or not 0 <= int(num) <= 65535:
        return f"SRV {label} must be a number between 0 and 65535"
    if not re.fullmatch(r'[A-Za-z0-9_*\-./]+', parts[3]):
      return f"{parts[3]} is not a valid SRV target"
  elif record_type == "CAA":
    # flags tag "value"
    parts = v.split(None, 2)
    if len(parts) != 3:
      return 'A CAA value must be: flags tag "value"'
    if not parts[0].isdigit() or not 0 <= int(parts[0]) <= 255:
      return "CAA flags must be a number between 0 and 255"
    if not re.fullmatch(r'[A-Za-z0-9]+', parts[1]):
      return "A CAA tag must be alphanumeric, such as issue or issuewild"
    if not (parts[2].startswith('"') and parts[2].endswith('"') and len(parts[2]) >= 2):
      return 'The CAA value must be in double quotes, such as "letsencrypt.org"'
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

  owner, name_err = _canonical_owner(record_name, zone_name)
  if name_err:
    return {"error": name_err}
  if record_type in _NAME_VALUED:
    record_value = _qualify_rdata(record_type, record_value)

  guard = bindctl.guard(zone_name, zone_file)

  err = _validate_rdata(record_type, record_value)
  if err:
    return {"error": err}

  # An exact duplicate is an error; the same name may legitimately carry several
  # records (round-robin A, an A alongside a TXT, and so on).
  if _find_rrs(zone_file, zone_name, name=owner, rtype=record_type, value=record_value):
    return {"error": f"Record {owner} {record_type} {record_value} already exists"}

  # A name holding a CNAME cannot hold any other data (RFC 1034 3.6.2).
  siblings = _find_rrs(zone_file, zone_name, name=owner)
  if record_type == 'CNAME' and siblings:
    return {"error": f"{owner} already has records; a CNAME cannot coexist with other data"}
  if any(rr['type'] == 'CNAME' for rr in siblings):
    return {"error": f"{owner} is a CNAME; it cannot also hold a {record_type} record"}

  # Add the record
  with open(zone_file, 'a') as f:
    f.write(f"{owner}\t\tIN {record_type}\t{record_value}\n")

  # Increment serial
  new_serial = increment_serial(zone_file)

  result = _commit_zone(guard, {"success": True, "serial": new_serial})
  if "error" in result:
    return result
  if create_ptr and record_type in ("A", "AAAA"):
    result["ptr"] = _create_ptr_record(owner, record_value, zone_name, zones,
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

  new_owner, name_err = _canonical_owner(new_record_name, zone_name)
  if name_err:
    return {"error": name_err}
  if record_type in _NAME_VALUED:
    record_value = _qualify_rdata(record_type, record_value)

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
                replacement=f"{new_owner}\t\tIN {record_type}\t{record_value}\n")

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
      # Whether a zone is dynamic is advisory. It depends on rndc reaching a
      # running server, so it must never be the reason a zone fails to load.
      try:
        zone["dynamic"] = bindctl.zone_is_dynamic(zone_name)
        if zone["dynamic"]:
          bindctl.sync_zone(zone_name)
      except Exception:
        zone["dynamic"] = False
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

  # Drop any marker comment we previously added, so re-saving does not stack up
  # copies of it alongside the statements it describes.
  zone_content = re.sub(r'^[ \t]*#[ \t]*Dynamic updates are enabled\..*$\n?',
                        '', zone_content, flags=re.MULTILINE)

  new_options = []
  if options.get('allowDynamicUpdates') and options.get('tsigKey'):
    # A marker in named.conf rather than in the zone file: BIND rewrites a
    # dynamic zone's file when it flushes the journal, so a header comment there
    # would not survive. This block is never rewritten by named.
    new_options.append('\t# Dynamic updates are enabled. BIND owns this zone file;'
                       ' edit records through Cockpit or nsupdate, not by hand.')
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


# ---------------------------------------------------------------------------
# Zone import
#
# Migrating off yast2-dns-server means moving zones onto a new box. The uploaded
# named.conf is the manifest: it carries the authoritative zone name, the type,
# and for secondaries the primaries list, none of which a zone file alone can
# supply.
# ---------------------------------------------------------------------------

def _read_stdin():
  """Bulk payloads arrive on stdin; a zone file can exceed ARG_MAX."""
  return sys.stdin.read()


def _addresses_in_clause(conf_text, zone_name, keywords):
  """Pull the addresses out of a primaries/masters/forwarders clause.

  Scoped to the named zone's own block so a clause in options or in a
  neighbouring zone is not picked up by mistake.
  """
  header = re.compile(rf'zone\s+"{re.escape(zone_name)}"\s+(?:in\s+)?\{{',
                      re.IGNORECASE)
  m = header.search(conf_text)
  if not m:
    return []
  block, _ = _extract_block(conf_text, conf_text.index('{', m.start()))

  for kw in keywords:
    hit = re.search(rf'\b{kw}\s*\{{', block, re.IGNORECASE)
    if not hit:
      continue
    inner, _ = _extract_block(block, block.index('{', hit.start()))
    found = []
    for token in inner.replace('\n', ' ').split(';'):
      token = token.strip()
      if not token:
        continue
      # Entries may carry a port or key; only the address is needed here.
      addr = token.split()[0]
      try:
        ipaddress.ip_address(addr)
      except ValueError:
        continue
      found.append(addr)
    if found:
      return found
  return []


def import_parse_conf(conf_text):
  """Read the zone declarations out of an uploaded named.conf.

  named-checkconf is advisory here, not a gate. A config from another server
  routinely fails it on this machine for reasons that have nothing to do with
  its zones: `include` directives point at paths that do not exist here, and
  statements such as `forward only;` depend on a `forwarders` clause supplied by
  one of those includes. Refusing to parse on that basis would reject most real
  configurations. The zone blocks are extracted regardless, and the checkconf
  output is passed along so the admin can judge it.
  """
  local = {z['name'].rstrip('.').lower() for z in read_zones()}

  # Includes are not followed: they reference the source server's filesystem.
  # Zones defined inside them will not appear below, so say so.
  includes = re.findall(r'^\s*include\s+"([^"]+)"\s*;', conf_text, re.MULTILINE)

  with tempfile.NamedTemporaryFile('w', suffix='.conf', delete=False) as tmp:
    tmp.write(conf_text)
    tmp_path = tmp.name

  try:
    ok, msg = bindctl.check_conf(tmp_path)

    zones = []
    conf_body = conf_text
    for z in parse_named_conf(tmp_path):
      name = z['name']
      name_err = _validate_zone_name(name)
      # Only a primary holds locally authored data. A secondary transfers its
      # contents and a forward zone has none at all.
      needs_file = z['type'] == 'Primary'
      entry = {
        "name": name,
        "type": z['type'],
        "sourceFile": z.get('file'),
        "needsFile": needs_file,
        "isDefault": _is_default_zone(name),
        "existsLocally": name.rstrip('.').lower() in local,
        "invalid": name_err,
      }
      # A secondary is defined by where it transfers from and a forward zone by
      # where it sends queries. Without these the zone cannot be recreated, so
      # they have to travel with the manifest.
      if z['type'] == 'Secondary':
        entry['primaries'] = _addresses_in_clause(conf_body, name,
                                                  ('primaries', 'masters'))
      elif z['type'] == 'Forward':
        entry['forwarders'] = _addresses_in_clause(conf_body, name, ('forwarders',))
      zones.append(entry)

    if not zones:
      return {"error": "No zone declarations were found in that file.",
              "detail": msg if not ok else ""}

    return {"success": True, "zones": zones, "includes": includes,
            "confValid": ok, "confMessage": "" if ok else msg}
  finally:
    Path(tmp_path).unlink(missing_ok=True)


def import_validate_zone(zone_name, content):
  """Check an uploaded zone file against the origin named.conf declares."""
  name_err = _validate_zone_name(zone_name)
  if name_err:
    return {"ok": False, "message": name_err}

  with tempfile.NamedTemporaryFile('w', suffix='.zone', delete=False) as tmp:
    tmp.write(content)
    tmp_path = tmp.name
  try:
    ok, msg = bindctl.check_zone(zone_name, tmp_path)
    return {"ok": ok, "message": msg}
  finally:
    Path(tmp_path).unlink(missing_ok=True)


def import_zone(meta, content):
  """Register one zone from an import. Validates before anything is written."""
  zone_name = (meta.get('name') or '').strip()
  zone_type = meta.get('type') or 'Primary'
  replace = bool(meta.get('replace'))
  normalize = meta.get('normalize', True)

  name_err = _validate_zone_name(zone_name)
  if name_err:
    return {"zone": zone_name, "error": name_err}

  existing = next((z for z in read_zones() if z['name'] == zone_name), None)
  if existing and not replace:
    return {"zone": zone_name,
            "error": f"{zone_name} already exists locally; not replaced"}

  if zone_type != 'Primary':
    # Nothing to write: a secondary's contents arrive by transfer and a forward
    # zone has none. Register the declaration and stop.
    if existing:
      return {"zone": zone_name, "error": f"{zone_name} already exists locally"}
    if zone_type == 'Secondary':
      result = create_zone(zone_name, 'Secondary', None, None,
                           primaries=meta.get('primaries') or [])
    else:
      result = create_zone(zone_name, 'Forward', None, None,
                           forwarders=meta.get('forwarders') or [])
    if 'error' in result:
      return {"zone": zone_name, "error": result['error']}
    return {"zone": zone_name, "imported": True, "type": zone_type,
            "reload": result.get('reload')}

  if not content or not content.strip():
    return {"zone": zone_name, "error": "No zone file was supplied"}

  # Validate before touching anything the server reads.
  with tempfile.NamedTemporaryFile('w', suffix='.zone', delete=False) as tmp:
    tmp.write(content)
    tmp_path = tmp.name
  try:
    ok, msg = bindctl.check_zone(zone_name, tmp_path)
    if not ok:
      return {"zone": zone_name, "error": "The zone file did not pass named-checkzone",
              "detail": msg}

    notes = []
    if normalize:
      norm_ok, norm_msg = bindctl.normalize_zone(zone_name, tmp_path)
      notes.append("Rewritten in canonical form by named-compilezone"
                   if norm_ok else norm_msg)

    # Give the imported zone a current serial. This never moves the number
    # backwards: if the source is somehow ahead of today's date it goes to
    # source + 1 instead. A serial lower than what secondaries already hold
    # would leave them convinced they are current and serving stale data.
    new_serial = increment_serial(tmp_path)
    if new_serial:
      notes.append(f"Serial set to {new_serial}")

    zone_file = f"{ZONES_BASE}/master/{zone_name}"
    Path(f"{ZONES_BASE}/master").mkdir(parents=True, exist_ok=True)
    backup = bindctl.snapshot(zone_file) if Path(zone_file).exists() else None

    shutil.copyfile(tmp_path, zone_file)
    os.chmod(zone_file, 0o644)
  finally:
    Path(tmp_path).unlink(missing_ok=True)

  if existing:
    # Already declared in named.conf; only the contents changed.
    return {"zone": zone_name, "imported": True, "replaced": True,
            "backup": backup, "notes": notes,
            "reload": bindctl.reload_zone(zone_name)}

  conf_backup = bindctl.snapshot(NAMED_CONF)
  try:
    with open(NAMED_CONF, 'a') as f:
      f.write(f"\nzone \"{zone_name}\" in {{\n\ttype master;\n"
              f"\tfile \"master/{zone_name}\";\n}};\n")
  except Exception as e:
    Path(zone_file).unlink(missing_ok=True)
    return {"zone": zone_name, "error": f"Failed to update named.conf: {e}"}

  err = bindctl.verify_conf_or_restore(conf_backup, NAMED_CONF)
  if err:
    Path(zone_file).unlink(missing_ok=True)
    return {"zone": zone_name, "error": err}

  return {"zone": zone_name, "imported": True, "notes": notes,
          "reload": bindctl.reconfig()}


# ---------------------------------------------------------------------------
# Raw named.conf editing
#
# The file is read and written verbatim. Stripping comments for display would
# destroy them on save, and a stock SUSE named.conf is mostly documentation --
# including commented-out settings people uncomment later.
# ---------------------------------------------------------------------------

def read_named_conf():
  """Return the live named.conf as text."""
  try:
    with open(NAMED_CONF, 'r') as f:
      return {"success": True, "path": NAMED_CONF, "content": f.read()}
  except Exception as e:
    return {"error": f"Could not read {NAMED_CONF}: {e}"}


def write_named_conf(content):
  """Validate and install a new named.conf, restoring the old one on failure."""
  if not content or not content.strip():
    return {"error": "Refusing to write an empty named.conf"}

  problems = _lint_named_conf(content)

  backup = bindctl.snapshot(NAMED_CONF)
  try:
    with open(NAMED_CONF, 'w') as f:
      f.write(content)
  except Exception as e:
    return {"error": f"Could not write {NAMED_CONF}: {e}"}

  err = bindctl.verify_conf_or_restore(backup, NAMED_CONF)
  if err:
    return {"error": err, "backup": backup}

  return {"success": True, "backup": backup, "warnings": problems,
          "reload": bindctl.reconfig()}


# Known options and the shape their values take. named.conf accepts far more
# than this, so an unrecognised key is passed through untouched and left to
# named-checkconf; the schema exists to turn common typos into a useful message
# rather than a parser error.
_OPTION_SCHEMA = {
  "recursion": ("bool", None),
  "notify": ("enum", ("yes", "no", "explicit", "master-only", "primary-only")),
  "stale-answer-enable": ("bool", None),
  "dnssec-validation": ("enum", ("yes", "no", "auto")),
  "forward": ("enum", ("first", "only")),
  "check-names": ("enum", ("warn", "fail", "ignore")),
  "auth-nxdomain": ("bool", None),
  "empty-zones-enable": ("bool", None),
  "minimal-responses": ("enum", ("yes", "no", "no-auth", "no-auth-recursive")),
  "directory": ("quoted", None),
  "dump-file": ("quoted", None),
  "statistics-file": ("quoted", None),
  "managed-keys-directory": ("quoted", None),
  "version": ("quoted", None),
  "server-id": ("quoted", None),
  "tcp-clients": ("number", None),
  "max-cache-size": ("size", None),
  "max-cache-ttl": ("duration", None),
  "lame-ttl": ("duration", None),
}


def lint_named_conf(content):
  """Check a buffer without writing it: schema first, then named-checkconf.

  This runs against a temporary copy so the editor can report problems with
  line numbers before anything touches the live file.
  """
  problems = _lint_named_conf(content)
  with tempfile.NamedTemporaryFile('w', suffix='.conf', delete=False) as tmp:
    tmp.write(content)
    tmp_path = tmp.name
  try:
    ok, msg = bindctl.check_conf(tmp_path)
  finally:
    Path(tmp_path).unlink(missing_ok=True)
  # checkconf reports the temporary path; the editor only cares about the line.
  msg = msg.replace(tmp_path, "named.conf")
  return {"schema": problems, "checkconfOk": ok, "checkconf": msg}


def _lint_named_conf(content):
  """Advisory checks against the option schema. Returns a list of messages."""
  problems = []
  simple = re.compile(r'^\s*([a-z][a-z0-9-]*)\s+([^;{}]+);\s*(?:#.*)?$', re.IGNORECASE)

  for lineno, raw in enumerate(content.splitlines(), start=1):
    line = raw.split('#')[0].split('//')[0]
    if not line.strip():
      continue
    m = simple.match(line)
    if not m:
      continue
    key, value = m.group(1).lower(), m.group(2).strip()
    if key not in _OPTION_SCHEMA:
      continue

    kind, allowed = _OPTION_SCHEMA[key]
    bad = None
    if kind == "bool" and value.lower() not in ("yes", "no"):
      bad = "expected yes or no"
    elif kind == "enum" and value.lower() not in allowed:
      bad = f"expected one of {', '.join(allowed)}"
    elif kind == "quoted" and not (value.startswith('"') and value.endswith('"')):
      bad = "expected a quoted string"
    elif kind == "number" and not value.isdigit():
      bad = "expected a number"
    elif kind == "duration" and not re.fullmatch(r'\d+[smhdw]?', value, re.IGNORECASE):
      bad = "expected a number, optionally suffixed with s, m, h, d or w"
    elif kind == "size" and not re.fullmatch(r'(\d+[kmg]?|unlimited|default)', value,
                                             re.IGNORECASE):
      bad = "expected a size such as 256m, or unlimited"

    if bad:
      problems.append(f"line {lineno}: {key} {value} -- {bad}")

  return problems


# ---------------------------------------------------------------------------
# Logging
#
# Output goes to syslog only. On a real deployment these records are either
# forwarded to something like Splunk or kept by the local journal, and neither
# needs BIND managing its own log files, rotation and disk budget. Dropping file
# channels removes the whole versions/size surface along with them.
# ---------------------------------------------------------------------------

_LOG_CATEGORIES = [
  ("default", "Anything without a category of its own"),
  ("general", "Messages that fit nowhere more specific"),
  ("queries", "Every query received. High volume."),
  ("query-errors", "Queries that could not be answered"),
  ("security", "Approved and denied requests"),
  ("xfer-in", "Zone transfers this server receives"),
  ("xfer-out", "Zone transfers this server sends"),
  ("update", "Dynamic update requests"),
  ("update-security", "Approved and denied update requests"),
  ("notify", "NOTIFY messages"),
  ("client", "Client activity"),
  ("lame-servers", "Misconfigured remote servers. Often noise."),
  ("dnssec", "DNSSEC validation"),
  ("resolver", "Recursive resolution"),
  ("network", "Network operations"),
  ("config", "Configuration file parsing and processing"),
  ("rate-limit", "Rate limiting activity"),
]

_LOG_SEVERITIES = ["critical", "error", "warning", "notice", "info", "debug"]
_LOG_FACILITIES = ["daemon", "local0", "local1", "local2", "local3",
                   "local4", "local5", "local6", "local7"]

# Channels this plugin generates are named predictably so they can be told
# apart from anything hand-written.
_LOG_CHANNEL_PREFIX = "cockpit_syslog_"


def _find_logging_block(content):
  """Return (start, end) of the top-level logging block, or None."""
  for m in re.finditer(r'^\s*logging\s*\{', content, re.MULTILINE):
    brace = content.index('{', m.start())
    _, end = _extract_block(content, brace)
    return m.start(), end
  return None


def read_logging():
  """Current logging settings, and whether they are ones we can represent."""
  if not Path(NAMED_CONF).exists():
    return {"error": "named.conf not found"}

  with open(NAMED_CONF, 'r') as f:
    content = f.read()

  span = _find_logging_block(content)
  if not span:
    return {"success": True, "enabled": False, "facility": "daemon",
            "categories": {}, "managed": True,
            "available": _LOG_CATEGORIES, "severities": _LOG_SEVERITIES,
            "facilities": _LOG_FACILITIES}

  body = content[span[0]:span[1]]

  # Map channel name -> severity, for the channels we generated.
  channels = {}
  facility = "daemon"
  foreign_channel = False
  for cm in re.finditer(r'channel\s+"?([A-Za-z0-9_.-]+)"?\s*\{', body):
    cname = cm.group(1)
    cbody, _ = _extract_block(body, body.index('{', cm.start()))
    sev = re.search(r'severity\s+([A-Za-z]+)\s*;', cbody)
    fac = re.search(r'syslog\s+([A-Za-z0-9]+)\s*;', cbody)
    if fac:
      facility = fac.group(1)
    if cname.startswith(_LOG_CHANNEL_PREFIX) and sev:
      channels[cname] = sev.group(1).lower()
    else:
      # A file channel, or one someone wrote by hand.
      foreign_channel = True

  categories = {}
  for gm in re.finditer(r'category\s+"?([A-Za-z0-9_.-]+)"?\s*\{([^}]*)\}', body):
    cat = gm.group(1)
    targets = [t.strip() for t in gm.group(2).split(';') if t.strip()]
    known = [channels[t] for t in targets if t in channels]
    if len(targets) == 1 and known:
      categories[cat] = known[0]
    else:
      foreign_channel = True

  return {"success": True, "enabled": True, "facility": facility,
          "categories": categories, "managed": not foreign_channel,
          "available": _LOG_CATEGORIES, "severities": _LOG_SEVERITIES,
          "facilities": _LOG_FACILITIES,
          "raw": body if foreign_channel else ""}


def write_logging(settings):
  """Replace the logging block with one built from the given settings."""
  enabled = bool(settings.get("enabled"))
  facility = settings.get("facility", "daemon")
  categories = settings.get("categories") or {}

  if facility not in _LOG_FACILITIES:
    return {"error": f"{facility} is not a syslog facility this page manages"}

  known_cats = {c for c, _ in _LOG_CATEGORIES}
  for cat, sev in categories.items():
    if cat not in known_cats:
      return {"error": f"{cat} is not a logging category this page manages"}
    if sev not in _LOG_SEVERITIES:
      return {"error": f"{sev} is not a valid severity"}

  if enabled and categories:
    used = sorted(set(categories.values()))
    lines = ["logging {"]
    for sev in used:
      lines.append(f"\tchannel {_LOG_CHANNEL_PREFIX}{sev} {{")
      lines.append(f"\t\tsyslog {facility};")
      lines.append(f"\t\tseverity {sev};")
      lines.append("\t\tprint-category yes;")
      lines.append("\t\tprint-severity yes;")
      lines.append("\t};")
    for cat in sorted(categories):
      lines.append(f"\tcategory {cat} {{ {_LOG_CHANNEL_PREFIX}{categories[cat]}; }};")
    lines.append("};")
    new_block = "\n".join(lines) + "\n"
  else:
    # Removing the block restores BIND's built-in defaults.
    new_block = ""

  with open(NAMED_CONF, 'r') as f:
    content = f.read()

  span = _find_logging_block(content)
  if span:
    tail = content[span[1]:]
    trimmed = tail.lstrip(';')
    updated = content[:span[0]] + new_block + trimmed
  elif new_block:
    updated = content.rstrip('\n') + "\n\n" + new_block
  else:
    return {"success": True, "unchanged": True}

  backup = bindctl.snapshot(NAMED_CONF)
  with open(NAMED_CONF, 'w') as f:
    f.write(updated)

  err = bindctl.verify_conf_or_restore(backup, NAMED_CONF)
  if err:
    return {"error": err}

  return {"success": True, "reload": bindctl.reconfig()}


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

  elif command == "read-logging":
    print(json.dumps(read_logging()))

  elif command == "write-logging" and len(sys.argv) >= 3:
    print(json.dumps(write_logging(json.loads(sys.argv[2]))))

  elif command == "read-named-conf":
    print(json.dumps(read_named_conf()))

  elif command == "lint-named-conf":
    print(json.dumps(lint_named_conf(_read_stdin())))

  elif command == "write-named-conf":
    print(json.dumps(write_named_conf(_read_stdin())))

  elif command == "import-parse-conf":
    print(json.dumps(import_parse_conf(_read_stdin())))

  elif command == "import-validate-zone" and len(sys.argv) >= 3:
    print(json.dumps(import_validate_zone(sys.argv[2], _read_stdin())))

  elif command == "import-zone" and len(sys.argv) >= 3:
    meta = json.loads(sys.argv[2])
    print(json.dumps(import_zone(meta, _read_stdin())))

  else:
    print(json.dumps({"error": f"Unknown command: {command}"}))
    sys.exit(1)


if __name__ == "__main__":
  main()
