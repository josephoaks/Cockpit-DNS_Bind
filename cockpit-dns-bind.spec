#
# spec file for package cockpit-dns-bind
#
# Copyright (c) 2026 Joseph Oaks
#
# License: LGPL-2.1
#
Name:           cockpit-dns-bind
Version:        0.1.1
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
