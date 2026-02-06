#
# spec file for package cockpit-dns-bind
#
# Copyright (c) 2026 Joseph Oaks
#
# License: LGPL-2.1
#

Name:           cockpit-dns-bind
Version:        0.1.0
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

# Safety: ensure no build artifacts
find . -type d -name "__pycache__" -prune -exec rm -rf {} +
find . -type d -name "node_modules" -prune -exec rm -rf {} +

%install
mkdir -p %{buildroot}/usr/share/cockpit
cp -a dns-bind %{buildroot}/usr/share/cockpit/

%files
%license LICENSE
%doc README.md
/usr/share/cockpit/dns-bind

%changelog
* Thu Feb 05 2026 Joseph Oaks
- Initial RPM packaging for dns-bind
- Zone management interface
- DNS record management (A, AAAA, CNAME, MX, TXT, PTR, NS, SOA)
- Forwarder configuration
- TSIG key management
