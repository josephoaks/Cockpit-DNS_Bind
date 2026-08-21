#
# spec file for package cockpit-dns-bind
#
# Copyright (c) 2026 Joseph Oaks
#
# License: LGPL-2.1
#
Name:           cockpit-dns-bind
Version:        0.3.0
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
install -d -m 0700 %{buildroot}%{_sharedstatedir}/cockpit-dns-bind
install -d -m 0700 %{buildroot}%{_sharedstatedir}/cockpit-dns-bind/backups

%files
%license LICENSE
%doc README.md
/usr/share/cockpit/dns-bind
# Backups may contain a named.conf with inline TSIG secrets, and zone files
# disclose internal network layout, so the directory is root-only and owned by
# the package rather than being created at first write with an inherited umask.
%dir %attr(0700, root, root) %{_sharedstatedir}/cockpit-dns-bind
%dir %attr(0700, root, root) %{_sharedstatedir}/cockpit-dns-bind/backups

%changelog
* Fri Aug 21 2026 Joseph Oaks
- Added: dynamic zones are now handled safely. A zone with allow-update or
  update-policy is frozen before its file is edited and thawed afterwards, so
  changes are no longer lost to the journal, and its records are synced from
  the journal before being read so the list matches what is being served.
- Added: a warning is shown when a zone accepts dynamic updates, and a comment
  is written into its named.conf block noting that BIND owns the zone file.
- Added: a Logging tab. Selected categories are sent to syslog at a chosen
  severity and facility. A logging block written by hand is detected and
  reported rather than replaced.
- Added: a Backups tab. Every change is snapshotted first, and any version can
  be previewed against the current file and restored. A backup is validated
  before it is put back, and the file it replaces is itself backed up.
- Added: SRV and CAA records can now be created and edited, using per-field
  forms rather than raw record data.
- Added: an editor for named.conf, with validation against named-checkconf
  and known option values, automatic backup, and rollback if the file does
  not load.
- Changed: backups are stored in /var/lib/cockpit-dns-bind/backups as files
  readable only by root, and are kept for ten versions or ninety days per file.
- Fixed: record names are now written fully qualified. A name entered as
  "host.example.com" without a trailing dot became host.example.com.example.com,
  and a name outside the zone was accepted and then ignored by named.
- Fixed: the domain name inside MX and SRV record data was qualified by
  appending a dot to the whole value, which was correct only because the name
  happens to come last.
- Fixed: saving a zone's options repeatedly added a duplicate comment to its
  named.conf block each time.

* Thu Aug 20 2026 Joseph Oaks
- Added: zone import. Upload the named.conf from an existing BIND server to
  read its zone declarations, then attach the zone files and register the
  zones locally.
- Added: uploaded named.conf is validated with named-checkconf before being
  parsed, and each uploaded zone file is validated with named-checkzone
  before anything is written. A zone that fails validation is not imported
  and its checkzone output is shown.
- Added: the import review table lists every declared zone with its type and
  expected file. Zones that ship with a stock named.conf are listed but not
  selected, and secondary and forward zones import without a zone file.
- Added: imported zones are given a current serial. The serial never moves
  backwards, so secondaries following the source server are not left
  believing they are up to date.
- Added: imported zone files are rewritten in canonical form with
  named-compilezone, so relative names are fully qualified and the stored
  file matches the format this plugin writes.
- Added: a zone that already exists locally is skipped unless replacing it is
  explicitly selected, and the existing file is backed up first.
- Changed: bulk payloads are passed to the backend on stdin rather than as a
  command line argument, so zone files larger than ARG_MAX can be imported.

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
