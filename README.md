# DNS/BIND Cockpit Plugin

A modern web-based management interface for BIND DNS servers, built as a Cockpit plugin using React and PatternFly 6. Designed for STIG compliance and enterprise security.

## Project Status

**Release Candidate** - All core functionality complete and tested

## Features

### ✅ Completed Features

#### Zone Management
- List all DNS zones with automatic filtering of system zones
- Create new zones with automatic SOA record generation
- Delete zones (removes both zone file and named.conf entry)
- Zone editor with intuitive breadcrumb navigation
- Tab-based interface (Basics, NS Records, MX Records, SOA, Records)

#### DNS Records (A/AAAA/CNAME/TXT/PTR)
- Add, edit, and delete DNS records via modal interface
- Automatic serial number increment on all changes (YYYYMMDDNN format)
- Support for multiple record types
- Individual record deletion with confirmation

#### SOA (Start of Authority) Records
- Two-column layout for organized viewing
- Time value inputs with unit selection (Seconds/Minutes/Hours/Days/Weeks)
- Parse and display existing SOA values
- Update timing values (Refresh, Retry, Expiration, Minimum, TTL)
- Primary Name Server and Contact Email set at zone creation
- Automatic serial number management

#### MX (Mail Exchange) Records
- Inline add interface (Address + Priority)
- Individual record deletion
- Automatic duplicate prevention
- Clean, streamlined UI

#### NS (Name Server) Records
- Inline add interface (Name Server)
- Individual record deletion
- Automatic duplicate prevention
- Clean, streamlined UI

#### Zone Basics Configuration
- **Allow Dynamic Updates** with TSIG key requirement
- **TSIG Key Selection** dropdown (populated from TSIG Keys page)
- **Enable Zone Transport** with ACL checkboxes (any, localhost, localnets)
- **Save Changes** button - writes configuration to named.conf
- **Clear Settings** button - removes allow-update and allow-transfer (only visible when settings exist)
- **Navigate to TSIG Keys** - link to create/manage keys (replaces inline creation)
- Validation: Requires TSIG key selection when dynamic updates enabled

#### TSIG Key Management (Complete)
- **List Keys** - Shows all keys from named.conf and /etc/named.d/
- **Generate Keys** - Create new keys with algorithm selection (HMAC-SHA256/SHA512/SHA1/MD5)
- **Upload from Desktop** - Validates format, checks conflicts, two-step import process
- **Browse Server** - Secure file browser restricted to 3 directories:
  - `/etc/named.d` (default key location)
  - `/tmp` (temporary storage)
  - User's home directory
- **Add Existing** - Import keys already on server
- **Delete Keys** - Remove from /etc/named.d/
- **Conflict Detection** - Overwrite confirmation modal for duplicate keys
- **File Validation** - Checks TSIG key format before importing
- **Secure Permissions** - Auto-sets 0o640 and attempts chown to named user

#### Secure File Browser
- **Directory Restrictions** - Cannot navigate outside 3 allowed directories
- **Quick Access Buttons** - Jump to /etc/named.d, /tmp, or home
- **Breadcrumb Navigation** - Click to navigate up directory tree
- **Visual Indicators** - Folder/file icons, parent directory (..) links
- **File Filtering** - Shows only .key files
- **Security Enforcement** - `isPathAllowed()` checks every navigation

#### ACL Management (Complete)
- **List ACLs** - Shows all ACL definitions from named.conf
- **Add ACL** - Name + multi-line textarea for IP/network/keyword entries
- **Edit ACL** - Modal interface for modifying existing ACLs
- **Delete ACL** - Remove from named.conf
- **Multi-line Input** - One IP/network/keyword per line
- **Format Support** - IPv4, IPv6, CIDR notation, keywords (localhost, localnets, any)
- **Validation** - ACL names must be alphanumeric with hyphens/underscores
- **STIG Compliance** - Supports explicit IP/network specification

#### DNS Forwarders (Complete)
- **Policy Selection** with STIG compliance indicators:
  - Merging forwarders is disabled
  - Automatic merging (forward first)
  - Merging forwarders is enabled ✓ STIG Recommended (forward only)
  - Custom configuration ✓ STIG Recommended
- **STIG Tooltips** - Green checkmark with hover explanation
- **Add Forwarders** - IPv4/IPv6 with strict validation:
  - Format validation (regex for IPv4/IPv6)
  - DNS response test (must respond to queries)
  - DNSSEC support test (checks for RRSIG records)
- **Validation Enforcement**:
  - ❌ Invalid DNS (no response) → REJECTED with error
  - ⚠️ Valid DNS but no DNSSEC → Warning + confirmation dialog
  - ✅ Valid DNS with DNSSEC → Accepted immediately
- **Persistent Storage** - DNSSEC validation results stored in `/var/lib/named/forwarder-validation.json`
- **Forwarder List** - Shows IP address and DNSSEC support status
- **Delete Forwarders** - Remove from configuration
- **Live Validation** - "Validating..." indicator during DNS/DNSSEC checks

#### Navigation & UX
- **Custom Event System** - Tab navigation without prop drilling
- **Conditional UI** - Buttons appear/hide based on state (Clear Settings, STIG indicators)
- **Loading States** - Spinners and "Validating..." text during async operations
- **Error Handling** - Clear error messages with dismissible alerts
- **Help Text** - Contextual guidance below inputs
- **Confirmation Dialogs** - For destructive actions (delete, clear, overwrite)

#### Reusable Components
- `TimeInput` - Consistent time value entry with unit selection
- `FileBrowserModal` - Secure, restricted file browser
- Custom event-based navigation system

## Technical Stack

### Frontend
- **Framework**: React 18
- **UI Library**: PatternFly 6
- **Build Tool**: Webpack
- **Language**: JavaScript (JSX, no TypeScript)
- **Code Style**: 2-space indentation
- **Styling**: 12px border radius, consistent color coding (green ✓, orange ⚠)

### Backend
- **Language**: Python 3
- **Communication**: Cockpit's `spawn` API
- **Architecture**: 4 separate backend scripts for clean separation of concerns
- **Configuration**: Direct file manipulation (`/etc/named.conf`, `/var/lib/named/master/`, `/etc/named.d/`)
- **Validation**: DNS queries via `dig`, format validation, DNSSEC checks

## Project Structure

```
dns-bind/
├── src/
│   ├── app.jsx                      # Main application with tab navigation
│   ├── components/
│   │   ├── ZonesPage.jsx           # Zone list view
│   │   ├── ZoneEditorPage.jsx      # Zone editor with 5 tabs
│   │   ├── TsigKeysPage.jsx        # TSIG key management (complete)
│   │   ├── AclsPage.jsx            # ACL management (complete)
│   │   ├── ForwardersPage.jsx      # DNS forwarder management (complete)
│   │   ├── FileBrowserModal.jsx    # Secure file browser
│   │   └── TimeInput.jsx           # Reusable time input component
│   ├── utils/
│   │   └── backend.js              # 4 spawn functions for backend communication
│   └── app.scss                    # Application styles
├── backend/
│   ├── dns-bind.py                 # Zone operations
│   ├── tsig-keys.py                # TSIG key management
│   ├── acls.py                     # ACL management
│   └── forwarders.py               # Forwarder management with validation
├── index.html                      # Entry point with branding CSS
├── build.sh                        # Build and deployment script
├── package.json
└── webpack.config.js
```

## Backend Architecture

### Separate Backend Scripts
Each backend script handles its own domain with clear separation of concerns:

**dns-bind.py** - Zone and record operations
**tsig-keys.py** - TSIG key lifecycle management
**acls.py** - ACL definitions in named.conf
**forwarders.py** - DNS forwarders with validation

### Backend Communication
```javascript
// 4 separate spawn functions in backend.js
spawnBackend()           // Zones, records, zone options
spawnTsigBackend()       // TSIG keys
spawnAclBackend()        // ACLs
spawnForwardersBackend() // Forwarders
```

## Backend API

### Zone Operations
```bash
# List all zones
backend/dns-bind.py list

# Get zone details
backend/dns-bind.py get <zone_name>

# Create new zone
backend/dns-bind.py create-zone '{"name":"example.com","type":"Primary","primary":"ns1.example.com.","contact":"admin.example.com."}'

# Delete zone
backend/dns-bind.py delete-zone '{"name":"example.com"}'

# Update zone options (Basics tab)
backend/dns-bind.py update-zone-options '{"zone":"example.com","allowDynamicUpdates":true,"tsigKey":"example-key","enableZoneTransport":true,"acls":["localhost"]}'
```

### Record Operations
```bash
# Add DNS record
backend/dns-bind.py add-record '{"zone":"example.com","name":"www","type":"A","value":"192.168.1.100"}'

# Update DNS record
backend/dns-bind.py update-record '{"zone":"example.com","oldName":"www","name":"www","type":"A","value":"192.168.1.101"}'

# Delete DNS record
backend/dns-bind.py delete-record '{"zone":"example.com","name":"www"}'
```

### MX/NS Record Operations
```bash
# Add MX record
backend/dns-bind.py add-mx-record '{"zone":"example.com","name":"@","priority":10,"mailserver":"mail.example.com"}'

# Delete MX record
backend/dns-bind.py delete-mx-record '{"zone":"example.com","name":"@","mailserver":"mail.example.com"}'

# Add NS record
backend/dns-bind.py add-ns-record '{"zone":"example.com","name":"example.com.","nameserver":"ns1.example.com."}'

# Delete NS record
backend/dns-bind.py delete-ns-record '{"zone":"example.com","name":"example.com.","nameserver":"ns1.example.com."}'
```

### SOA Operations
```bash
# Update SOA record
backend/dns-bind.py update-soa '{"zone":"example.com","primary":"ns1.example.com.","contact":"admin.example.com.","serial":2026020500,"refresh":"3h","retry":"1h","expiry":"1w","minimum":"1d","ttl":"2d"}'
```

### TSIG Key Operations
```bash
# List TSIG keys
backend/tsig-keys.py list

# Generate new TSIG key
backend/tsig-keys.py generate '{"name":"example-key","algorithm":"hmac-sha256"}'

# Upload key for validation
backend/tsig-keys.py upload '{"filename":"mykey.key","content":"key \"mykey\" { ... };"}'

# Import validated key
backend/tsig-keys.py import '{"temp_path":"/tmp/tsig-uploads/mykey.key","final_filename":"mykey.key","overwrite":false}'

# Add existing key from server
backend/tsig-keys.py add-existing '{"path":"/etc/named.d/mykey.key"}'

# Delete key
backend/tsig-keys.py delete '{"name":"example-key"}'

# Cleanup temp files
backend/tsig-keys.py cleanup '{"temp_path":"/tmp/tsig-uploads/temp.key"}'
```

### ACL Operations
```bash
# List ACLs
backend/acls.py list

# Add ACL
backend/acls.py add '{"name":"trusted","values":["192.168.1.0/24","10.0.0.5","localhost"]}'

# Update ACL
backend/acls.py update '{"name":"trusted","values":["192.168.1.0/24","localhost"]}'

# Delete ACL
backend/acls.py delete '{"name":"trusted"}'
```

### Forwarder Operations
```bash
# List forwarders and policy
backend/forwarders.py list

# Validate DNS server (checks DNS response and DNSSEC support)
backend/forwarders.py validate '{"ip":"8.8.8.8"}'

# Add forwarder
backend/forwarders.py add '{"ip":"8.8.8.8","validDns":true,"supportsDnssec":true}'

# Delete forwarder
backend/forwarders.py delete '{"ip":"8.8.8.8"}'

# Set forward policy
backend/forwarders.py set-policy '{"policy":"enabled"}'
```

## Installation

### Prerequisites
- SUSE Linux Enterprise Server 15 SP6 (or compatible)
- BIND DNS server installed and configured
- Cockpit web console installed
- Node.js and npm for building
- Python 3 with standard library

### Build and Install
```bash
# Clone the repository
cd /home/yourusername/src/dns-bind

# Install dependencies
npm install

# Build the plugin (includes backend deployment)
./build.sh

# The plugin will be installed to:
# /usr/share/cockpit/dns-bind/
```

### File Locations
- **Plugin files**: `/usr/share/cockpit/dns-bind/`
- **Backend scripts**: `/usr/share/cockpit/dns-bind/backend/`
  - `dns-bind.py`
  - `tsig-keys.py`
  - `acls.py`
  - `forwarders.py`
- **BIND config**: `/etc/named.conf`
- **Zone files**: `/var/lib/named/master/`
- **TSIG keys**: `/etc/named.d/`
- **Validation data**: `/var/lib/named/forwarder-validation.json`
- **Temp uploads**: `/tmp/tsig-uploads/`

## Design Decisions

### User Experience
- **Inline editing** for MX/NS records instead of modals
- **Vertical layouts** with single-column forms for clarity
- **Conditional UI** - buttons appear/hide based on context
- **STIG indicators** - green checkmarks with tooltips for compliance
- **Color coding** - green ✓ for success, orange ⚠ for warnings, red for errors
- **Loading states** - clear feedback during async operations

### Security & STIG Compliance
- **TSIG key requirement** for dynamic updates enforced at UI level
- **File validation** for all uploaded keys with format checking
- **Proper permissions** (640) automatically set on generated keys
- **Restricted file browser** - cannot navigate outside 3 allowed directories
- **DNS validation** - forwarders must respond to DNS queries
- **DNSSEC enforcement** - warning + confirmation for non-DNSSEC servers
- **ACL specificity** - encourages explicit IP/network definitions
- **Policy indicators** - visual cues for STIG-recommended options

### Architecture
- **Separation of concerns** - 4 backend scripts for different domains
- **Component reusability** - shared TimeInput, FileBrowserModal
- **Event-based navigation** - custom events avoid prop drilling
- **State management** in parent components for control
- **Backend validation** before modifying files
- **Persistent storage** for validation data

### Configuration Philosophy
- **Clean UI** - minimal clutter, contextual help text
- **Validation feedback** - clear error messages
- **Confirmation dialogs** - for destructive actions
- **Consistent styling** - 12px border radius throughout
- **Auto-save options** - immediate feedback on save operations

## STIG Compliance Features

### V-72367: ACL Management
✅ Configured ACLs for zone transfers and queries
✅ Specific IP/network definitions supported
✅ Visual interface for managing allow-transfer

### V-72369: Zone Transfer Control
✅ Zone transport configuration in Basics tab
✅ ACL selection (localhost, localnets, or custom)
✅ Clear/disable option for zone transfer

### V-72383: DNS Forwarders
✅ Authorized forwarder configuration
✅ DNS validation (must respond to queries)
✅ DNSSEC support checking
✅ STIG-recommended policies clearly marked

### V-72385: TSIG Keys
✅ Transaction signature key management
✅ Algorithm selection (HMAC-SHA256/SHA512 recommended)
✅ Secure key generation and storage
✅ Dynamic update authorization

## Development

### Building
```bash
npm run build
```

### Local Development
```bash
npm run watch
```

### Code Style
- 2-space indentation (JavaScript and Python)
- No TypeScript
- PatternFly 6 components preferred
- Functional React components with hooks
- Snake_case for Python, camelCase for JavaScript

## Tab Structure

1. **DNS Zones** - Zone list and zone editor (Basics, NS, MX, SOA, Records)
2. **Forwarders** - DNS forwarder configuration with STIG compliance
3. **ACLs** - Access control list management
4. **TSIG Keys** - Transaction signature key management

**Removed Tabs**:
- Start-Up (use Cockpit Services)
- Basic Options (set during BIND setup)
- Logging (managed via syslog)

## Testing Status

| Feature | Status |
|---------|--------|
| Zone list/add/delete | ✅ Tested |
| DNS records CRUD (A/AAAA/CNAME/TXT/PTR) | ✅ Tested |
| MX records add/delete | ✅ Tested |
| NS records add/delete | ✅ Tested |
| SOA updates | ✅ Tested |
| Zone Basics save/clear | ✅ Tested |
| TSIG key generation | ✅ Tested |
| TSIG key upload | ✅ Tested |
| TSIG key browse (file browser) | ✅ Tested |
| TSIG key delete | ✅ Tested |
| ACL add/edit/delete | ✅ Tested |
| Forwarder add with validation | ✅ Tested |
| Forwarder DNS validation | ✅ Tested |
| Forwarder DNSSEC validation | ✅ Tested |
| Forwarder policy changes | ✅ Tested |
| File browser security | ✅ Tested |
| Tab navigation | ✅ Tested |

## Known Issues

- None currently - all major features tested and working

## Future Enhancements

### Potential Additions
- [ ] Additional DNS record types (SRV, CAA, DKIM)
- [ ] Zone templates
- [ ] BIND server restart/reload controls
- [ ] Real-time zone file preview
- [ ] Bulk import/export
- [ ] DNSSEC zone signing
- [ ] Statistics/monitoring dashboard

## Contributing

This is release_candidate-ready software. When contributing:
1. Follow the 2-space indentation style
2. Test all backend operations manually before committing
3. Update this README with any new features or API changes
4. Maintain STIG compliance in all security-related features
5. Keep backend scripts separated by concern

## License

Apache-2.0 - see [LICENSE](LICENSE) file for details

## Acknowledgments

- Built for SUSE Linux Enterprise Server 15 SP6
- Uses Cockpit web console framework
- UI components from PatternFly 6
- Inspired by YaST DNS Server module
- Designed with STIG compliance in mind

## Author

**Joseph Oaks**

- GitHub: [@josephoaks](https://github.com/josephoaks)
- Repository: [Cockpit-DNS_Bind](https://github.com/josephoaks/Cockpit-DNS_Bind)

---

**Last Updated**: February 5, 2026
**Version**: 0.1.0 (Release Candidate)
**Status**: Complete - All Core Features Implemented
