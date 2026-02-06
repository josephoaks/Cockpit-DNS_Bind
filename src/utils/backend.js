// src/utils/backend.js
import cockpit from 'cockpit';

const DNS_BACKEND_PATH = "/usr/share/cockpit/dns-bind/backend/dns-bind.py";
const TSIG_BACKEND_PATH = "/usr/share/cockpit/dns-bind/backend/tsig-keys.py";
const ACL_BACKEND_PATH = "/usr/share/cockpit/dns-bind/backend/acls.py";
const FORWARDERS_BACKEND_PATH = "/usr/share/cockpit/dns-bind/backend/forwarders.py";

export function spawnBackend(args) {
  return new Promise((resolve, reject) => {
    const process = cockpit.spawn(['/usr/bin/python3', DNS_BACKEND_PATH, ...args], {
      superuser: "require",
      err: "out"
    });

    let stdout = "";

    process.stream((data) => {
      stdout += data;
    });

    process.then(() => {
      if (!stdout || stdout.trim() === "") {
        reject(new Error("Backend returned empty output"));
      } else {
        resolve(stdout);
      }
    }).catch((err) => {
      reject(new Error(err.message || "Backend failed"));
    });
  });
}

export function spawnTsigBackend(args) {
  return new Promise((resolve, reject) => {
    const process = cockpit.spawn(['/usr/bin/python3', TSIG_BACKEND_PATH, ...args], {
      superuser: "require",
      err: "out"
    });

    let stdout = "";

    process.stream((data) => {
      stdout += data;
    });

    process.then(() => {
      if (!stdout || stdout.trim() === "") {
        reject(new Error("Backend returned empty output"));
      } else {
        resolve(stdout);
      }
    }).catch((err) => {
      reject(new Error(err.message || "Backend failed"));
    });
  });
}

export function spawnAclBackend(args) {
  return new Promise((resolve, reject) => {
    const process = cockpit.spawn(['/usr/bin/python3', ACL_BACKEND_PATH, ...args], {
      superuser: "require",
      err: "out"
    });

    let stdout = "";

    process.stream((data) => {
      stdout += data;
    });

    process.then(() => {
      if (!stdout || stdout.trim() === "") {
        reject(new Error("Backend returned empty output"));
      } else {
        resolve(stdout);
      }
    }).catch((err) => {
      reject(new Error(err.message || "Backend failed"));
    });
  });
}

export function spawnForwardersBackend(args) {
  return new Promise((resolve, reject) => {
    const process = cockpit.spawn(['/usr/bin/python3', FORWARDERS_BACKEND_PATH, ...args], {
      superuser: "require",
      err: "out"
    });

    let stdout = "";

    process.stream((data) => {
      stdout += data;
    });

    process.then(() => {
      if (!stdout || stdout.trim() === "") {
        reject(new Error("Backend returned empty output"));
      } else {
        resolve(stdout);
      }
    }).catch((err) => {
      reject(new Error(err.message || "Backend failed"));
    });
  });
}
