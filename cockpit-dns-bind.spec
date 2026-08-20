#
# spec file for package cockpit-dns-bind
#
# Copyright (c) 2026 Joseph Oaks
#
# License: LGPL-2.1
#
Name:           cockpit-dns-bind
Version:        0.2.0
Release:        1%{?dist}
Summary:        Cockpit plugin for managing BIND DNS server
License:        LGPL-2.1
URL:            https://github.com/josephoaks/Cockpit-DNS_Bind
Source0:        cockpit-dns-bind-%{version}.tar.gz
BuildArch:      noarch
Requires:       cockpit
Requires:       bind
Requires:       python3

%description
Cockpit DNS Bind is a Cockpit web UI plugin that provides
comprehensive management of BIND DNS servers including zone
management, DNS records, forwarders, TSIG keys, and ACLs.
It is designed to work across transactional and traditional
Linux distributions.

%prep
%autosetup -n cockpit-dns-bind-%{version}

%build
# Nothing to build, tarball includes pre-built dist/

%install
mkdir -p %{buildroot}/usr/share/cockpit
cp -a dns-bind %{buildroot}/usr/share/cockpit/

%files
%license LICENSE
%doc README.md
/usr/share/cockpit/dns-bind

%changelog
* Thu Aug 20 2026 Joseph Oaks
- Fixed an issue with deletion of records that were non-A records.
- Fixed IPv6 reverse zones were filtered out of the zone list entirely,
  so an ip6.arpa zone could be created but never seen. Only BIND's
  default ::1 reverse zone is hidden now.
- Fixed Forwarder address validation accepted malformed IPv6 such as
  `::::::::` and rejected valid IPv4-mapped addresses such as
  `::ffff:192.168.1.1`.
- Fixed The zone type selected in the Add Zone dialog was ignored;
  every zone was created as a primary. Secondary and forward zones are
  now written correctly, with the fields each type actually needs.
- Fixed Removing a zone from named.conf used a pattern that could not
  span nested blocks, which would have corrupted the file when deleting
  a zone containing a `primaries` or `forwarders` block.
- Added A "Reverse" action on A and AAAA records creates the matching PTR
  for an existing record, for backfilling records added before the
  reverse zone existed.
- Added The Add Zone dialog can derive a reverse zone name from a
  network in CIDR notation, covering IPv4 and IPv6, networks spanning
  several zones, and prefixes longer than /24.
- Added Creating a zone now asks for confirmation, showing the resolved
  zone name and what will be created.
- Added Record values are validated before being written: A records
  must hold an IPv4 address and AAAA an IPv6 address, and CNAME, PTR
  and DNAME values must be single domain names.
- Added deleting of an A or AAAA records offers to remove the
  matching PTR that is matched on its name
- Added Creating a PTR for an address that already has one now warns
  and requires confirmation. Multiple PTRs per address can make
  reverse lookups non-deterministic and can break forward-confirmed
  reverse DNS.
- Added Reverse zone serials are now incremented when a PRT is create
  or removed.
- Added CNAME records are rejected where they would coexist with
  other data at the same name (RFC 1034 §3.6.2), which BIND refuses
  to load.
- Changed The message shown when no reverse zone hosts an address now
  names the zone that would be needed (for example `1.168.192.in-addr.arpa`).
* Mon Jul 20 2026 Joseph Oaks
- Fixed DNS Record TYPE parsing to include (AAAA, CNAME, TXT, PTR)
  and others that were missing. This was found due to an upgrade
  from Leap 15.6 to Leap 16, so an existing zone with records.
-Added sort and scroll to the Records.
-Added checkbox for adding of PTR records for reverse table.
* Thu Feb 05 2026 Joseph Oaks
- Initial RPM packaging for dns-bind
- Zone management interface
- DNS record management (A, AAAA, CNAME, MX, TXT, PTR, NS, SOA)
- Forwarder configuration
- TSIG key management
- ACL configuration support
