#!/bin/bash
npm run build
cp dist/* /usr/share/cockpit/dns-bind/
cp -r backend/ /usr/share/cockpit/dns-bind/
systemctl restart cockpit
