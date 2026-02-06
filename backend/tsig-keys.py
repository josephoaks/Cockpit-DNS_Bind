#!/usr/bin/python3
"""
TSIG Key Management Backend for DNS/BIND Cockpit Plugin
Handles TSIG key operations: list, generate, upload, import, delete
"""

import sys
import json
import os
import re
import subprocess
import shutil
from datetime import datetime
from pathlib import Path

# Configuration
NAMED_CONF = "/etc/named.conf"
NAMED_D_DIR = "/etc/named.d"
TMP_UPLOAD_DIR = "/tmp/tsig-uploads"

def ensure_tmp_dir():
  """Ensure temp upload directory exists with correct permissions"""
  os.makedirs(TMP_UPLOAD_DIR, mode=0o700, exist_ok=True)

def read_tsig_keys():
  """Read TSIG keys from named.conf and /etc/named.d/*.key files"""
  keys = []
  key_pattern = r'key\s+"([^"]+)"\s*\{[^}]*algorithm\s+([^;]+);[^}]*secret\s+"([^"]+)"'

  # Read from named.conf
  if Path(NAMED_CONF).exists():
    try:
      with open(NAMED_CONF, 'r') as f:
        content = f.read()
        for match in re.finditer(key_pattern, content, re.IGNORECASE | re.DOTALL):
          keys.append({
            "name": match.group(1),
            "algorithm": match.group(2).strip(),
            "secret": match.group(3),
            "source": "named.conf"
          })
    except Exception as e:
      return {"error": f"Failed to read {NAMED_CONF}: {str(e)}"}

  # Read from /etc/named.d/*.key files
  if Path(NAMED_D_DIR).exists():
    try:
      for key_file in Path(NAMED_D_DIR).glob("*.key"):
        with open(key_file, 'r') as f:
          content = f.read()
          for match in re.finditer(key_pattern, content, re.IGNORECASE | re.DOTALL):
            keys.append({
              "name": match.group(1),
              "algorithm": match.group(2).strip(),
              "secret": match.group(3),
              "source": str(key_file),
              "filename": key_file.name
            })
    except Exception as e:
      return {"error": f"Failed to read keys from {NAMED_D_DIR}: {str(e)}"}

  return {"keys": keys}

def validate_tsig_key_content(content):
  """
  Validate that content is a valid TSIG key
  Returns: (is_valid, key_name, algorithm, error_message)
  """
  # Remove comments and whitespace
  clean_content = re.sub(r'#.*$', '', content, flags=re.MULTILINE)
  clean_content = re.sub(r'//.*$', '', clean_content, flags=re.MULTILINE)

  # Check for key definition
  key_pattern = r'key\s+"([^"]+)"\s*\{[^}]*algorithm\s+([^;]+);[^}]*secret\s+"([^"]+)"'
  match = re.search(key_pattern, clean_content, re.IGNORECASE | re.DOTALL)

  if not match:
    return (False, None, None, "Invalid TSIG key format: missing key definition")

  key_name = match.group(1)
  algorithm = match.group(2).strip()
  secret = match.group(3)

  # Validate key name
  if not re.match(r'^[a-zA-Z0-9_\-\.]+$', key_name):
    return (False, None, None, f"Invalid key name: {key_name}")

  # Validate algorithm
  valid_algorithms = ['hmac-md5', 'hmac-sha1', 'hmac-sha256', 'hmac-sha512']
  if algorithm.lower() not in valid_algorithms:
    return (False, None, None, f"Invalid algorithm: {algorithm}")

  # Validate secret (base64)
  if not re.match(r'^[A-Za-z0-9+/=]+$', secret):
    return (False, None, None, "Invalid secret: must be base64 encoded")

  return (True, key_name, algorithm, None)

def check_key_exists(key_name):
  """Check if a key with this name already exists"""
  result = read_tsig_keys()
  if "error" in result:
    return False

  for key in result.get("keys", []):
    if key["name"] == key_name:
      return True
  return False

def generate_tsig_key(key_name, algorithm='hmac-sha256'):
  """Generate a new TSIG key using tsig-keygen"""
  try:
    # Use tsig-keygen (BIND 9.13+)
    result = subprocess.run(
      ['tsig-keygen', '-a', algorithm, key_name],
      capture_output=True,
      text=True,
      check=True
    )

    # Parse the output to extract the key block
    output = result.stdout

    # Extract the key block
    key_match = re.search(r'(key\s+"[^"]+"\s*\{[^}]+\});', output, re.DOTALL)
    if key_match:
      key_block = key_match.group(1)

      # Write to a separate file for organization
      key_file = f"{NAMED_D_DIR}/{key_name}.key"
      with open(key_file, 'w') as f:
        f.write(f"# TSIG key generated on {datetime.now()}\n")
        f.write(key_block + "\n")

      # Set proper permissions (readable only by root/named)
      os.chmod(key_file, 0o640)

      # Extract secret from the key block
      secret_match = re.search(r'secret\s+"([^"]+)"', key_block)
      algorithm_match = re.search(r'algorithm\s+([^;]+);', key_block)

      return {
        "success": True,
        "name": key_name,
        "algorithm": algorithm_match.group(1).strip() if algorithm_match else algorithm,
        "secret": secret_match.group(1) if secret_match else "",
        "file": key_file
      }

    return {"error": "Failed to parse generated key"}

  except subprocess.CalledProcessError:
    # Try ddns-confgen as fallback
    try:
      result = subprocess.run(
        ['ddns-confgen', '-a', algorithm, '-k', key_name],
        capture_output=True,
        text=True,
        check=True
      )

      output = result.stdout
      key_match = re.search(r'(key\s+"[^"]+"\s*\{[^}]+\});', output, re.DOTALL)

      if key_match:
        key_block = key_match.group(1)
        key_file = f"{NAMED_D_DIR}/{key_name}.key"

        with open(key_file, 'w') as f:
          f.write(f"# TSIG key generated on {datetime.now()}\n")
          f.write(key_block + "\n")

        os.chmod(key_file, 0o640)

        secret_match = re.search(r'secret\s+"([^"]+)"', key_block)
        algorithm_match = re.search(r'algorithm\s+([^;]+);', key_block)

        return {
          "success": True,
          "name": key_name,
          "algorithm": algorithm_match.group(1).strip() if algorithm_match else algorithm,
          "secret": secret_match.group(1) if secret_match else "",
          "file": key_file
        }

      return {"error": "Failed to parse generated key"}

    except Exception as e2:
      return {"error": f"Failed to generate TSIG key: {str(e2)}"}

  except Exception as e:
    return {"error": f"Failed to generate TSIG key: {str(e)}"}

def upload_tsig_key(filename, content):
  """
  Upload TSIG key to temp directory and validate
  Returns: {"status": "ok", "temp_path": path, "key_name": name} or {"error": message}
  """
  ensure_tmp_dir()

  # Validate content
  is_valid, key_name, algorithm, error = validate_tsig_key_content(content)
  if not is_valid:
    return {"error": error}

  # Check for conflicts
  if check_key_exists(key_name):
    return {
      "error": f"Key '{key_name}' already exists",
      "conflict": True,
      "key_name": key_name
    }

  # Write to temp file
  temp_path = os.path.join(TMP_UPLOAD_DIR, filename)
  try:
    with open(temp_path, 'w') as f:
      f.write(content)
    os.chmod(temp_path, 0o600)

    return {
      "status": "ok",
      "temp_path": temp_path,
      "key_name": key_name,
      "algorithm": algorithm
    }
  except Exception as e:
    return {"error": f"Failed to save uploaded file: {str(e)}"}

def import_tsig_key(temp_path, final_filename, overwrite=False):
  """
  Move key from temp to /etc/named.d/ and set permissions
  Returns: {"status": "ok", "path": final_path} or {"error": message}
  """
  if not os.path.exists(temp_path):
    return {"error": "Temporary file not found"}

  # Read and validate
  try:
    with open(temp_path, 'r') as f:
      content = f.read()

    is_valid, key_name, algorithm, error = validate_tsig_key_content(content)
    if not is_valid:
      return {"error": error}

    # Check for conflicts (unless overwrite)
    if not overwrite and check_key_exists(key_name):
      return {"error": f"Key '{key_name}' already exists"}

    # Ensure final filename ends with .key
    if not final_filename.endswith('.key'):
      final_filename += '.key'

    final_path = os.path.join(NAMED_D_DIR, final_filename)

    # Move file
    shutil.move(temp_path, final_path)
    os.chmod(final_path, 0o640)

    # Change ownership to named user if possible
    try:
      import pwd
      named_uid = pwd.getpwnam('named').pw_uid
      named_gid = pwd.getpwnam('named').pw_gid
      os.chown(final_path, named_uid, named_gid)
    except:
      # If named user doesn't exist, just leave as root
      pass

    return {
      "success": True,
      "path": final_path,
      "key_name": key_name,
      "algorithm": algorithm
    }

  except Exception as e:
    return {"error": f"Failed to import key: {str(e)}"}

def add_existing_key(server_path):
  """
  Import an existing key file from a server path
  Returns: {"success": True, ...} or {"error": message}
  """
  if not os.path.exists(server_path):
    return {"error": f"File not found: {server_path}"}

  # Read and validate
  try:
    with open(server_path, 'r') as f:
      content = f.read()

    is_valid, key_name, algorithm, error = validate_tsig_key_content(content)
    if not is_valid:
      return {"error": error}

    # Check for conflicts
    if check_key_exists(key_name):
      return {"error": f"Key '{key_name}' already exists"}

    # Copy to named.d directory
    filename = os.path.basename(server_path)
    if not filename.endswith('.key'):
      filename = f"{key_name}.key"

    dest_path = os.path.join(NAMED_D_DIR, filename)

    shutil.copy2(server_path, dest_path)
    os.chmod(dest_path, 0o640)

    # Change ownership to named user if possible
    try:
      import pwd
      named_uid = pwd.getpwnam('named').pw_uid
      named_gid = pwd.getpwnam('named').pw_gid
      os.chown(dest_path, named_uid, named_gid)
    except:
      pass

    return {
      "success": True,
      "path": dest_path,
      "key_name": key_name,
      "algorithm": algorithm
    }

  except Exception as e:
    return {"error": f"Failed to add existing key: {str(e)}"}

def delete_tsig_key(key_name):
  """
  Delete a TSIG key file from /etc/named.d/
  Returns: {"success": True} or {"error": message}
  """
  result = read_tsig_keys()
  if "error" in result:
    return result

  # Find the key
  key_to_delete = None
  for key in result.get("keys", []):
    if key["name"] == key_name:
      key_to_delete = key
      break

  if not key_to_delete:
    return {"error": f"Key '{key_name}' not found"}

  # Only delete keys from named.d directory
  source = key_to_delete.get("source", "")
  if source == "named.conf":
    return {"error": "Cannot delete keys from named.conf directly. Please edit named.conf manually."}

  # Delete the file
  try:
    if os.path.exists(source):
      os.unlink(source)
      return {"success": True, "deleted": key_name}
    else:
      return {"error": f"Key file not found: {source}"}
  except Exception as e:
    return {"error": f"Failed to delete key: {str(e)}"}

def cleanup_temp_key(temp_path):
  """
  Remove a temporary key file
  Returns: {"success": True} or {"error": message}
  """
  try:
    if os.path.exists(temp_path):
      os.unlink(temp_path)
      return {"success": True}
    return {"error": "Temporary file not found"}
  except Exception as e:
    return {"error": f"Failed to cleanup temp file: {str(e)}"}

def main():
  if len(sys.argv) < 2:
    print(json.dumps({"error": "No command provided"}))
    sys.exit(1)

  command = sys.argv[1]

  if command == "list":
    result = read_tsig_keys()
    print(json.dumps(result))

  elif command == "generate" and len(sys.argv) >= 3:
    data = json.loads(sys.argv[2])
    result = generate_tsig_key(data['name'], data.get('algorithm', 'hmac-sha256'))
    print(json.dumps(result))

  elif command == "upload" and len(sys.argv) >= 3:
    data = json.loads(sys.argv[2])
    result = upload_tsig_key(data['filename'], data['content'])
    print(json.dumps(result))

  elif command == "import" and len(sys.argv) >= 3:
    data = json.loads(sys.argv[2])
    result = import_tsig_key(
      data['temp_path'],
      data['final_filename'],
      data.get('overwrite', False)
    )
    print(json.dumps(result))

  elif command == "add-existing" and len(sys.argv) >= 3:
    data = json.loads(sys.argv[2])
    result = add_existing_key(data['path'])
    print(json.dumps(result))

  elif command == "delete" and len(sys.argv) >= 3:
    data = json.loads(sys.argv[2])
    result = delete_tsig_key(data['name'])
    print(json.dumps(result))

  elif command == "cleanup" and len(sys.argv) >= 3:
    data = json.loads(sys.argv[2])
    result = cleanup_temp_key(data['temp_path'])
    print(json.dumps(result))

  else:
    print(json.dumps({"error": f"Unknown command: {command}"}))
    sys.exit(1)

if __name__ == "__main__":
  main()
