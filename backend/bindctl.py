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
import shutil
import subprocess
import sys
import time
from pathlib import Path

NAMED_CONF = "/etc/named.conf"
BACKUP_DIR = "/var/lib/cockpit-dns-bind/backups"
KEEP_BACKUPS = 10
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

def snapshot(path):
  """Copy a file aside before it is modified. Returns the backup path or None.

  Backups live outside the zone directory so named never sees them, and are
  timestamped so a bad change can be walked back more than one step.
  """
  src = Path(path)
  if not src.exists():
    return None
  try:
    Path(BACKUP_DIR).mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    dest = Path(BACKUP_DIR) / f"{src.name}.{stamp}.{os.getpid()}"
    shutil.copy2(src, dest)
    _prune(src.name)
    return str(dest)
  except Exception:
    # A failed backup must not block the edit; it only removes the safety net.
    return None


def _prune(basename):
  try:
    kept = sorted(Path(BACKUP_DIR).glob(f"{basename}.*"), reverse=True)
    for old in kept[KEEP_BACKUPS:]:
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


def guard(zone_name, zone_file):
  """Snapshot a zone file and record whether it was already valid.

  named-checkzone applies full integrity checks, and plenty of working zones
  fail them for reasons that predate any edit (an NS target with no address
  record, for instance). Rolling back on a pre-existing failure would make such
  a zone permanently uneditable, so the before state is what decides whether a
  later failure is attributable to this change.
  """
  ok, _ = check_zone(zone_name, zone_file)
  return {"zone": zone_name, "file": zone_file,
          "backup": snapshot(zone_file), "was_valid": ok}


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
