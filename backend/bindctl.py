#!/usr/bin/python3
"""Validation, backup/restore, and reload helpers for the BIND backends.

Imported by the other backend scripts (Python puts the script's own directory
on sys.path, so a plain `import bindctl` works), and usable directly as a CLI
for the Reload button in the UI.

Two rules drive the design:

  * Validate before reloading. A malformed zone file does not stop named -- it
    keeps serving the last good copy and logs the error, which from the UI is
    indistinguishable from nothing happening. named-checkzone tells us up front.

  * reload is not reconfig. `rndc reload <zone>` rereads one zone file. It will
    not pick up a zone that was just added to named.conf; that needs
    `rndc reconfig`. Using the wrong one makes a new zone look created but never
    served.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import quote, unquote

NAMED_CONF = "/etc/named.conf"
BACKUP_DIR = "/var/lib/cockpit-dns-bind/backups"
KEEP_BACKUPS = 10
KEEP_DAYS = 90
SERVICE = "named"


def _run(cmd, timeout=15):
  """Run a command, returning (returncode, combined output)."""
  try:
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return p.returncode, (p.stdout + p.stderr).strip()
  except FileNotFoundError:
    return 127, f"{cmd[0]} not found"
  except subprocess.TimeoutExpired:
    return 124, f"{cmd[0]} timed out"
  except Exception as e:  # pragma: no cover - defensive
    return 1, str(e)


def _have(binary):
  return shutil.which(binary) is not None


# --------------------------------------------------------------------------
# Service state
# --------------------------------------------------------------------------

def named_running():
  rc, _ = _run(["systemctl", "is-active", "--quiet", SERVICE])
  if rc == 0:
    return True
  # systemd may be unavailable in a container; fall back to a process check.
  rc, _ = _run(["pgrep", "-x", "named"])
  return rc == 0


def rndc_usable():
  """rndc needs a control channel and a key; report why it is not usable."""
  if not _have("rndc"):
    return False, "rndc is not installed"
  rc, out = _run(["rndc", "status"])
  if rc == 0:
    return True, ""
  return False, out or "rndc could not reach named"


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------

def check_conf(conf_path=None):
  """Validate named.conf. Returns (ok, message)."""
  path = conf_path or NAMED_CONF
  if not _have("named-checkconf"):
    return True, "named-checkconf is not installed; configuration was not validated"
  rc, out = _run(["named-checkconf", path])
  return rc == 0, out


def check_zone(zone_name, zone_file):
  """Validate a zone file against its origin. Returns (ok, message)."""
  if not zone_file or not Path(zone_file).exists():
    return True, ""
  if not _have("named-checkzone"):
    return True, "named-checkzone is not installed; the zone file was not validated"
  rc, out = _run(["named-checkzone", zone_name, zone_file])
  return rc == 0, out


# --------------------------------------------------------------------------
# Backup / restore
# --------------------------------------------------------------------------

_STAMP_SUFFIX = re.compile(r'\.(\d{8}-\d{6})\.(\d+)$')

# Backups are flat files whose name is the percent-encoded absolute path of the
# file they came from, plus a timestamp. Encoding rather than mirroring the
# directory tree keeps the origin recoverable without recreating a filesystem
# root inside the state directory.
def _encode_origin(path):
  return quote(str(path), safe='')


def _decode_origin(name):
  return unquote(name)


def _ensure_backup_dir():
  """Create the backup directory root-owned and private.

  Backups can contain a named.conf with inline TSIG secrets, and zone files
  disclose internal network layout, so neither the directory nor its contents
  are readable by anyone but root.
  """
  root = Path(BACKUP_DIR)
  root.mkdir(parents=True, exist_ok=True)
  os.chmod(root, 0o700)
  return root


def snapshot(path):
  """Copy a file aside before it is modified. Returns the backup path or None.

  Backups live outside the zone directory so named never sees them, and are
  timestamped so a bad change can be walked back more than one step.
  """
  src = Path(path)
  if not src.exists():
    return None
  try:
    root = _ensure_backup_dir()
    stamp = time.strftime("%Y%m%d-%H%M%S")
    dest = root / f"{_encode_origin(src.resolve())}.{stamp}.{os.getpid()}"
    # copyfile rather than copy2: the source mode is 0644 and must not carry
    # over to a file that may contain key material.
    shutil.copyfile(src, dest)
    os.chmod(dest, 0o600)
    _prune(_encode_origin(src.resolve()))
    return str(dest)
  except Exception:
    # A failed backup must not block the edit; it only removes the safety net.
    return None


def original_path_of(backup_path):
  """The file a backup was taken from, or None if the path is not a backup."""
  try:
    entry = Path(backup_path).resolve()
    entry.relative_to(Path(BACKUP_DIR).resolve())
  except Exception:
    return None
  m = _STAMP_SUFFIX.search(entry.name)
  if not m:
    return None
  origin = _decode_origin(entry.name[:m.start()])
  # An encoded name always decodes to an absolute path; anything else means the
  # file was not written by snapshot().
  return origin if origin.startswith('/') else None


def list_backups():
  """Every backup on disk, newest first, grouped by the file it came from."""
  root = Path(BACKUP_DIR)
  if not root.exists():
    return []

  by_origin = {}
  for entry in root.iterdir():
    if not entry.is_file():
      continue
    origin = original_path_of(entry)
    if not origin:
      continue
    m = _STAMP_SUFFIX.search(entry.name)
    stat = entry.stat()
    by_origin.setdefault(origin, []).append({
      "backup": str(entry),
      "taken": m.group(1),
      "size": stat.st_size,
      "mtime": int(stat.st_mtime),
    })

  out = []
  for origin, versions in sorted(by_origin.items()):
    versions.sort(key=lambda v: v["mtime"], reverse=True)
    out.append({"path": origin, "exists": Path(origin).exists(), "versions": versions})
  return out


def read_backup(backup_path):
  """Contents of one backup, for previewing before a restore."""
  origin = original_path_of(backup_path)
  if not origin:
    return {"error": "That path is not inside the backup directory"}
  try:
    with open(backup_path, 'r') as f:
      content = f.read()
  except Exception as e:
    return {"error": f"Could not read the backup: {e}"}

  current = ""
  if Path(origin).exists():
    try:
      with open(origin, 'r') as f:
        current = f.read()
    except Exception:
      current = ""
  return {"success": True, "path": origin, "content": content, "current": current}


def restore_backup(backup_path, zone_name=None):
  """Put a backup back, validating it first.

  Restoring is itself a change worth undoing, so the file being replaced is
  snapshotted before it is overwritten. The restored content is validated in
  place and rolled back if it does not load, because a backup is not
  automatically good -- it may predate a fix, or have been taken from a file
  that was already broken.
  """
  origin = original_path_of(backup_path)
  if not origin:
    return {"error": "That path is not inside the backup directory"}
  if not Path(backup_path).exists():
    return {"error": "That backup no longer exists"}

  is_conf = os.path.abspath(origin) == os.path.abspath(NAMED_CONF)

  # Validate the backup before it goes anywhere near the live file.
  if is_conf:
    ok, msg = check_conf(backup_path)
  elif zone_name:
    ok, msg = check_zone(zone_name, backup_path)
  else:
    ok, msg = True, ""
  if not ok:
    return {"error": "That backup does not pass validation, so it was not restored.",
            "detail": msg}

  undo = snapshot(origin) if Path(origin).exists() else None
  try:
    shutil.copy2(backup_path, origin)
  except Exception as e:
    return {"error": f"Could not write {origin}: {e}"}

  if is_conf:
    err = verify_conf_or_restore(undo, origin)
    if err:
      return {"error": err}
    return {"success": True, "path": origin, "undo": undo, "reload": reconfig()}

  if zone_name:
    ok, msg = check_zone(zone_name, origin)
    if not ok:
      restore(undo, origin)
      return {"error": f"Restore rejected and the previous file was put back. {msg}"}
    return {"success": True, "path": origin, "undo": undo,
            "reload": reload_zone(zone_name)}

  return {"success": True, "path": origin, "undo": undo, "reload": reconfig()}


def _prune(encoded_origin):
  """Keep the most recent KEEP_BACKUPS copies of one file, and drop anything
  older than KEEP_DAYS regardless of count, so the directory cannot grow without
  bound on a busy server."""
  try:
    root = Path(BACKUP_DIR)
    kept = sorted(root.glob(f"{encoded_origin}.*"), reverse=True)
    cutoff = time.time() - (KEEP_DAYS * 86400)
    for i, old in enumerate(kept):
      if i >= KEEP_BACKUPS or old.stat().st_mtime < cutoff:
        old.unlink(missing_ok=True)
  except Exception:
    pass


def restore(backup_path, target):
  """Put a snapshot back. Returns True on success."""
  if not backup_path or not Path(backup_path).exists():
    return False
  try:
    shutil.copy2(backup_path, target)
    return True
  except Exception:
    return False


def zone_is_dynamic(zone_name):
  """Is this zone under BIND's control via dynamic update?

  Asked of the running server rather than inferred from named.conf, because
  `rndc zonestatus` is authoritative and covers both allow-update and
  update-policy. With named down there is no journal to conflict with, so a
  direct file edit is safe and this reports False.
  """
  if not named_running():
    return False
  usable, _ = rndc_usable()
  if not usable:
    return False
  rc, out = _run(["rndc", "zonestatus", zone_name])
  if rc != 0:
    return False
  return re.search(r'^\s*dynamic:\s*yes\s*$', out, re.MULTILINE | re.IGNORECASE) is not None


def freeze_zone(zone_name):
  """Suspend dynamic updates and flush the journal to the zone file.

  Editing the file of a dynamic zone without this loses the change: BIND holds
  pending updates in a .jnl journal and will overwrite or ignore whatever was
  written underneath it.
  """
  rc, out = _run(["rndc", "freeze", zone_name])
  return rc == 0, out


def thaw_zone(zone_name):
  """Resume dynamic updates. This reloads the zone, so no separate reload."""
  rc, out = _run(["rndc", "thaw", zone_name])
  return rc == 0, out


def sync_zone(zone_name):
  """Write pending journal entries out to the zone file.

  Used before reading a dynamic zone so the records shown match what is being
  served rather than the last on-disk state.
  """
  rc, out = _run(["rndc", "sync", zone_name])
  return rc == 0, out


def guard(zone_name, zone_file):
  """Snapshot a zone file and record whether it was already valid.

  named-checkzone applies full integrity checks, and plenty of working zones
  fail them for reasons that predate any edit (an NS target with no address
  record, for instance). Rolling back on a pre-existing failure would make such
  a zone permanently uneditable, so the before state is what decides whether a
  later failure is attributable to this change.
  """
  ok, _ = check_zone(zone_name, zone_file)

  # A dynamic zone must be frozen before its file is touched, and the freeze
  # flushes the journal so what we then read and rewrite is current.
  frozen = False
  freeze_error = None
  if zone_is_dynamic(zone_name):
    frozen, msg = freeze_zone(zone_name)
    if not frozen:
      freeze_error = msg or f"Could not freeze {zone_name}"

  return {"zone": zone_name, "file": zone_file,
          "backup": snapshot(zone_file), "was_valid": ok,
          "dynamic": frozen or freeze_error is not None,
          "frozen": frozen, "freezeError": freeze_error}


def verify_or_restore(g):
  """Validate a just-written zone file. Returns (error, warning).

  error   -- the change broke a previously valid zone and was rolled back
  warning -- the zone has problems, but it had them before this change too
  """
  ok, msg = check_zone(g["zone"], g["file"])
  if ok:
    return None, None

  if not g["was_valid"]:
    return None, (f"Your change was saved, but {g['zone']} does not pass "
                  f"named-checkzone and did not before this change either. "
                  f"named will not load it until this is fixed: {msg}")

  if restore(g["backup"], g["file"]):
    return f"Change rejected and the zone file was restored. {msg}", None
  return f"Change rejected and the zone file could NOT be restored. {msg}", None


def verify_conf_or_restore(backup_path, conf_path=None):
  """Same, for named.conf."""
  path = conf_path or NAMED_CONF
  ok, msg = check_conf(path)
  if ok:
    return None
  if restore(backup_path, path):
    return f"Change rejected and named.conf was restored. {msg}"
  return f"Change rejected and named.conf could NOT be restored. {msg}"


# --------------------------------------------------------------------------
# Reload
# --------------------------------------------------------------------------

def normalize_zone(zone_name, zone_file):
  """Rewrite a zone file in canonical form. Returns (ok, message).

  named-compilezone expands $ORIGIN, fully qualifies relative names, and
  canonicalizes whitespace, so an imported zone ends up in the same shape the
  plugin writes and the zone parser sees something predictable. The stored file
  will not match the admin's original byte for byte, which is why callers say
  so in their result.
  """
  if not _have("named-compilezone"):
    return False, "named-compilezone is not installed; the zone was stored as uploaded"
  out_path = f"{zone_file}.normalized"
  rc, out = _run(["named-compilezone", "-f", "text", "-F", "text",
                  "-o", out_path, zone_name, zone_file])
  if rc != 0:
    Path(out_path).unlink(missing_ok=True)
    return False, out
  try:
    shutil.move(out_path, zone_file)
  except Exception as e:
    Path(out_path).unlink(missing_ok=True)
    return False, str(e)
  return True, ""


def _service_reload(reason):
  rc, out = _run(["systemctl", "reload", SERVICE])
  if rc == 0:
    return {"status": "reloaded", "via": "systemctl",
            "message": f"Reloaded {SERVICE} with systemctl ({reason})"}
  return {"status": "failed", "via": "systemctl",
          "message": f"Could not reload {SERVICE}: {out or 'systemctl reload failed'}"}


def _reload(args, label):
  """Shared path for reload and reconfig, with soft failure and fallback."""
  if not named_running():
    return {"status": "not-running",
            "message": f"Changes were saved, but {SERVICE} is not running, "
                       f"so nothing is being served yet. Start it to apply them."}

  usable, why = rndc_usable()
  if not usable:
    result = _service_reload(why)
    if result["status"] == "reloaded":
      result["message"] += f". rndc was unavailable: {why}"
    return result

  rc, out = _run(["rndc"] + args)
  if rc == 0:
    return {"status": "reloaded", "via": "rndc", "message": f"{label} succeeded"}
  return {"status": "failed", "via": "rndc",
          "message": f"Changes were saved, but {label} failed: {out or 'rndc reported an error'}"}


def reload_zone(zone_name=None):
  """Reread a single zone file, or every zone when no name is given."""
  if zone_name:
    return _reload(["reload", zone_name], f"rndc reload {zone_name}")
  return _reload(["reload"], "rndc reload")


def reconfig():
  """Reread named.conf and pick up added or removed zones."""
  return _reload(["reconfig"], "rndc reconfig")


def status():
  running = named_running()
  usable, why = rndc_usable()
  conf_ok, conf_msg = check_conf()
  return {
    "running": running,
    "rndc": usable,
    "rndcMessage": why,
    "configValid": conf_ok,
    "configMessage": conf_msg,
  }


def main():
  cmd = sys.argv[1] if len(sys.argv) > 1 else "status"

  if cmd == "status":
    print(json.dumps(status()))
  elif cmd == "reload":
    print(json.dumps(reload_zone(sys.argv[2] if len(sys.argv) > 2 else None)))
  elif cmd == "reconfig":
    print(json.dumps(reconfig()))
  elif cmd == "list-backups":
    print(json.dumps(list_backups()))
  elif cmd == "read-backup" and len(sys.argv) >= 3:
    print(json.dumps(read_backup(sys.argv[2])))
  elif cmd == "restore-backup" and len(sys.argv) >= 3:
    print(json.dumps(restore_backup(sys.argv[2],
                                    sys.argv[3] if len(sys.argv) > 3 else None)))
  elif cmd == "check-conf":
    ok, msg = check_conf()
    print(json.dumps({"ok": ok, "message": msg}))
  elif cmd == "check-zone" and len(sys.argv) >= 4:
    ok, msg = check_zone(sys.argv[2], sys.argv[3])
    print(json.dumps({"ok": ok, "message": msg}))
  else:
    print(json.dumps({"error": f"Unknown command: {cmd}"}))
    sys.exit(1)


if __name__ == "__main__":
  main()
