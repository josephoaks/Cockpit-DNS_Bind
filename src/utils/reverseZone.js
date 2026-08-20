// Derive in-addr.arpa / ip6.arpa zone names from a network in CIDR notation.
//
// A reverse zone boundary has to fall on a label: an octet for IPv4, a nibble
// for IPv6. Networks that don't align to one either span several zones or
// require classless delegation (RFC 2317), so this reports what it would
// actually create rather than silently rounding.

const v4 = (cidr) => {
  const [addr, prefixStr] = cidr.split('/');
  const octets = addr.split('.');
  if (octets.length !== 4) return { error: 'Expected four octets, e.g. 192.168.1.0/24' };

  const nums = octets.map((o) => (/^\d{1,3}$/.test(o) ? Number(o) : NaN));
  if (nums.some((n) => Number.isNaN(n) || n > 255)) {
    return { error: `${addr} is not a valid IPv4 address` };
  }
  if (prefixStr === undefined) return { error: 'Add a prefix length, e.g. /24' };
  const prefix = Number(prefixStr);
  if (!Number.isInteger(prefix) || prefix < 8 || prefix > 32) {
    return { error: 'IPv4 prefix must be between /8 and /32' };
  }

  const nameFor = (o, labels) => `${o.slice(0, labels).reverse().join('.')}.in-addr.arpa`;

  // Classless: no zone of its own; the containing /24 is what holds the PTRs.
  if (prefix > 24) {
    const base = [nums[0], nums[1], nums[2], 0];
    return {
      zones: [nameFor(base, 3)],
      note: `A /${prefix} is smaller than one reverse zone. PTRs for these addresses `
        + `live in the containing /24 unless your upstream has delegated the range to `
        + `you with RFC 2317 classless delegation, which this dialog does not set up.`,
    };
  }

  const aligned = Math.ceil(prefix / 8) * 8;
  const labels = aligned / 8;
  const count = 2 ** (aligned - prefix);
  if (count > 16) {
    return {
      error: `A /${prefix} spans ${count} reverse zones. Create them individually, `
        + `or use a /${aligned} or longer prefix.`,
    };
  }

  // Zero the host part, then step through each aligned block the network covers.
  const varying = labels - 1;
  const start = nums.slice(0, labels);
  start[varying] = start[varying] & (256 - 2 ** (aligned - prefix));

  const zones = [];
  for (let i = 0; i < count; i += 1) {
    const block = start.slice();
    block[varying] = start[varying] + i;
    zones.push(nameFor(block, labels));
  }
  return {
    zones,
    note: count > 1 ? `A /${prefix} covers ${count} reverse zones; each is created separately.` : null,
  };
};

const expandV6 = (addr) => {
  if (addr.includes(':::')) return null;
  if ((addr.match(/::/g) || []).length > 1) return null;
  // A single leading or trailing colon is only legal as part of "::".
  if (/^:[^:]/.test(addr) || /[^:]:$/.test(addr)) return null;
  const [head, tail] = addr.split('::');
  const headParts = head ? head.split(':').filter(Boolean) : [];
  const tailParts = tail ? tail.split(':').filter(Boolean) : [];
  if (!addr.includes('::') && headParts.length !== 8) return null;
  const fill = 8 - headParts.length - tailParts.length;
  if (fill < 0) return null;
  const groups = [...headParts, ...Array(addr.includes('::') ? fill : 0).fill('0'), ...tailParts];
  if (groups.length !== 8) return null;
  if (groups.some((g) => !/^[0-9a-fA-F]{1,4}$/.test(g))) return null;
  return groups.map((g) => g.padStart(4, '0')).join('').toLowerCase();
};

const v6 = (cidr) => {
  const [addr, prefixStr] = cidr.split('/');
  const nibbles = expandV6(addr);
  if (!nibbles) return { error: `${addr} is not a valid IPv6 address` };
  if (prefixStr === undefined) return { error: 'Add a prefix length, e.g. /64' };
  const prefix = Number(prefixStr);
  if (!Number.isInteger(prefix) || prefix < 4 || prefix > 128) {
    return { error: 'IPv6 prefix must be between /4 and /128' };
  }

  const aligned = Math.floor(prefix / 4) * 4;
  const used = aligned / 4;
  const zone = `${nibbles.slice(0, used).split('').reverse().join('.')}.ip6.arpa`;
  return {
    zones: [zone],
    note: prefix % 4 !== 0
      ? `A /${prefix} does not fall on a nibble boundary; the zone shown covers the `
        + `containing /${aligned}.`
      : null,
  };
};

const v4Address = (addr) => {
  const octets = addr.split('.');
  if (octets.length !== 4) return false;
  return octets.every((o) => /^\d{1,3}$/.test(o) && Number(o) <= 255);
};

// Validates IPv4 and IPv6 literals, including the IPv4-mapped form
// (::ffff:192.168.1.1) that a naive hex-group regex rejects.
export const isIpAddress = (input) => {
  const addr = (input || '').trim();
  if (!addr) return false;
  if (!addr.includes(':')) return v4Address(addr);

  const lastColon = addr.lastIndexOf(':');
  const tailIsV4 = addr.slice(lastColon + 1).includes('.');
  if (tailIsV4) {
    const v4part = addr.slice(lastColon + 1);
    if (!v4Address(v4part)) return false;
    const nums = v4part.split('.').map(Number);
    const asGroups = `${((nums[0] << 8) | nums[1]).toString(16)}:${((nums[2] << 8) | nums[3]).toString(16)}`;
    return expandV6(`${addr.slice(0, lastColon)}:${asGroups}`) !== null;
  }
  return expandV6(addr) !== null;
};

// Zones that ship in a stock named.conf and are not the admin's to manage.
// The IPv6 test has to cover both loopback forms distributions use: ::1
// (a leading 1) and :: (all zeros). Matching "ip6.arpa" broadly would hide
// every IPv6 reverse zone the admin creates, which is the bug this replaces.
export const isDefaultZone = (name) => {
  const n = (name || '').trim().replace(/\.$/, '').toLowerCase();
  if (!n || n === '.') return true;
  if (n === 'localhost' || n === 'localhost.localdomain') return true;
  if (/(^|\.)127\.in-addr\.arpa$/.test(n)) return true;
  if (n === '0.in-addr.arpa' || n === '255.in-addr.arpa') return true;
  if (n === '0.ip6.arpa') return true;
  // The loopback/unspecified reverse zones: all-zero nibbles with an optional
  // leading 1. The label count is not pinned because shipped configs vary --
  // SLES declares this zone with 31 nibbles rather than 32.
  if (/^[01](\.0){27,31}\.ip6\.arpa$/.test(n)) return true;
  return false;
};

export const reverseZonesFor = (input) => {
  const cidr = (input || '').trim();
  if (!cidr) return null;
  if (!cidr.includes('/')) return { error: 'Enter a network in CIDR notation, e.g. 192.168.1.0/24' };
  return cidr.includes(':') ? v6(cidr) : v4(cidr);
};
