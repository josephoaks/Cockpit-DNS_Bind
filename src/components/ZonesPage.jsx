import React, { useEffect, useState } from 'react';
import {
  Button,
  Checkbox,
  Form,
  FormGroup,
  Modal,
  ModalBody,
  ModalFooter,
  ModalVariant,
  PageSection,
  TextInput,
  Toolbar,
  ToolbarContent,
  ToolbarItem,
  Spinner,
  Alert,
} from '@patternfly/react-core';
import { PlusIcon } from '@patternfly/react-icons';
import { spawnBackend, spawnBindctl, reloadNotice } from '../utils/backend';
import { reverseZonesFor, isDefaultZone } from '../utils/reverseZone';
import { ZoneEditorPage } from './ZoneEditorPage';
import { ZoneImportModal } from './ZoneImportModal';
import { NamedConfEditor } from './NamedConfEditor';

export const ZonesPage = () => {
  const [view, setView] = useState('list'); // 'list' or 'edit'
  const [currentZone, setCurrentZone] = useState(null);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [ldapSupport, setLdapSupport] = useState(false);
  const [zones, setZones] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  // Modal form state
  const [newZoneName, setNewZoneName] = useState('');
  const [newZoneType, setNewZoneType] = useState('Primary');
  const [newZonePrimary, setNewZonePrimary] = useState('');
  const [newZoneContact, setNewZoneContact] = useState('');
  const [newZoneNetwork, setNewZoneNetwork] = useState('');
  const [newZonePrimaries, setNewZonePrimaries] = useState('');
  const [newZoneForwarders, setNewZoneForwarders] = useState('');
  const [bindStatus, setBindStatus] = useState(null);
  const [reloading, setReloading] = useState(false);
  const [notice, setNotice] = useState(null);
  const [isImportOpen, setIsImportOpen] = useState(false);
  const [isConfOpen, setIsConfOpen] = useState(false);

  const reverseHint = reverseZonesFor(newZoneNetwork);

  // Load zones on mount
  useEffect(() => {
    if (view === 'list') {
      loadZones();
      loadBindStatus();
    }
  }, [view]);

  const loadZones = async () => {
    try {
      setLoading(true);
      setError(null);
      const output = await spawnBackend(['list']);
      const allZones = JSON.parse(output);

      // Hide the zones a stock named.conf ships with; everything else is the
      // admin's, including any IPv6 reverse zone they created.
      const userZones = allZones.filter(zone => !isDefaultZone(zone.name));

      setZones(userZones);
      setLoading(false);
    } catch (err) {
      console.error('Failed to load zones:', err);
      setError('Failed to load DNS zones: ' + err.message);
      setLoading(false);
    }
  };

  const handleModalToggle = () => {
    setIsModalOpen(!isModalOpen);
    // Reset form when closing
    if (isModalOpen) {
      setNewZoneName('');
      setNewZoneType('Primary');
      setNewZonePrimary('');
      setNewZoneContact('');
    }
  };

  const loadBindStatus = async () => {
    try {
      setBindStatus(JSON.parse(await spawnBindctl(['status'])));
    } catch (err) {
      console.error('Failed to read BIND status:', err);
      setBindStatus(null);
    }
  };

  const handleReload = async () => {
    setReloading(true);
    setNotice(null);
    try {
      // Zones are added and removed here, so named.conf has to be reread;
      // a plain reload would not pick up a zone that was just created.
      const result = JSON.parse(await spawnBindctl(['reconfig']));
      setNotice(result.status === 'reloaded'
        ? { variant: 'success', text: result.message }
        : { variant: result.status === 'not-running' ? 'warning' : 'danger', text: result.message });
    } catch (err) {
      setNotice({ variant: 'danger', text: 'Reload failed: ' + err.message });
    } finally {
      setReloading(false);
      await loadBindStatus();
    }
  };

  const handleAddZone = async () => {
    const name = newZoneName.trim();
    if (!name) {
      alert('Zone name is required');
      return;
    }

    // A network typed into the Zone Name field is a common slip, and the two
    // fields sit next to each other. Work out what they meant and offer it.
    if (name.includes('/')) {
      const derived = reverseZonesFor(name);
      if (derived && derived.zones && derived.zones.length === 1) {
        if (confirm(`${name} is a network, not a zone name.\n\n`
          + `The reverse zone for it is ${derived.zones[0]}.\n\nUse that instead?`)) {
          setNewZoneName(derived.zones[0]);
        }
        return;
      }
      alert(`${name} is a network, not a zone name. Use the reverse zone helper `
        + `below the Zone Name field to work out the right name.`);
      return;
    }

    const splitAddrs = (s) => s.split(/[\s,]+/).map((a) => a.trim()).filter(Boolean);
    const data = { name, type: newZoneType };
    let summary;

    if (newZoneType === 'Secondary') {
      const primaries = splitAddrs(newZonePrimaries);
      if (!primaries.length) {
        alert('A secondary zone needs at least one primary server address');
        return;
      }
      data.primaries = primaries;
      summary = `Secondary zone, transferred from: ${primaries.join(', ')}`;
    } else if (newZoneType === 'Forward') {
      const forwarders = splitAddrs(newZoneForwarders);
      if (!forwarders.length) {
        alert('A forward zone needs at least one forwarder address');
        return;
      }
      data.forwarders = forwarders;
      summary = `Forward zone, queries sent to: ${forwarders.join(', ')}`;
    } else {
      if (!newZonePrimary.trim() || !newZoneContact.trim()) {
        alert('Primary name server and contact email are required');
        return;
      }
      data.primary = newZonePrimary.trim();
      data.contact = newZoneContact.trim();
      summary = `Primary zone with a new zone file\nSOA: ${data.primary} / ${data.contact}`;
    }

    // Zone names are easy to mistype and awkward to correct after the fact,
    // so confirm the exact name before anything is written.
    if (!confirm(`Create this zone?\n\n${name}\n\n${summary}`)) return;

    try {
      const output = await spawnBackend(['create-zone', JSON.stringify(data)]);
      const result = JSON.parse(output);

      if (result.error) {
        setError('Failed to create zone: ' + result.error);
        return;
      }

      setNotice(result.warning
        ? { variant: 'warning', text: result.warning }
        : reloadNotice(result));

      // Reload zones list
      await loadZones();
      await loadBindStatus();
      handleModalToggle();
    } catch (err) {
      console.error('Failed to create zone:', err);
      setError('Failed to create zone: ' + err.message);
    }
  };

  const handleDeleteZone = async (zoneName) => {
    if (!confirm(`Delete zone ${zoneName}?`)) return;

    try {
      const data = { name: zoneName };
      const output = await spawnBackend(['delete-zone', JSON.stringify(data)]);
      const result = JSON.parse(output);

      if (result.error) {
        setError('Failed to delete zone: ' + result.error);
        return;
      }

      // Reload zones list
      await loadZones();
    } catch (err) {
      console.error('Failed to delete zone:', err);
      setError('Failed to delete zone: ' + err.message);
    }
  };

  const handleEditZone = (zone) => {
    setCurrentZone(zone);
    setView('edit');
  };

  const handleBackToList = () => {
    setView('list');
    setCurrentZone(null);
  };

  // If editing a zone, show the zone editor
  if (view === 'edit' && currentZone) {
    return <ZoneEditorPage zone={currentZone} onBack={handleBackToList} />;
  }

  // Otherwise show the zones list
  if (loading) {
    return (
      <PageSection padding={{ default: 'padding' }}>
        <Spinner size="xl" />
      </PageSection>
    );
  }

  return (
    <PageSection padding={{ default: 'padding' }}>
      {error && (
        <Alert
          variant="danger"
          title={error}
          isInline
          actionClose={<Button variant="plain" onClick={() => setError(null)}>×</Button>}
          style={{ marginBottom: '1rem' }}
        />
      )}

      {/* LDAP Support checkbox */}
      <div style={{ marginBottom: '2rem' }}>
        <Checkbox
          label="LDAP Support Active"
          isChecked={ldapSupport}
          onChange={(event, checked) => setLdapSupport(checked)}
          id="ldap-support-checkbox"
        />
      </div>

      {/* Toolbar with Add Zone button */}
      <div style={{ marginBottom: '2rem' }}>
        <Toolbar>
          <ToolbarContent>
            <ToolbarItem>
              <Button
                variant="primary"
                icon={<PlusIcon />}
                onClick={handleModalToggle}
              >
                Add Zone
              </Button>
            </ToolbarItem>
            <ToolbarItem>
              <Button variant="secondary" onClick={() => setIsImportOpen(true)}>
                Import Zones
              </Button>
            </ToolbarItem>
            <ToolbarItem>
              <Button variant="secondary" onClick={() => setIsConfOpen(true)}>
                Edit named.conf
              </Button>
            </ToolbarItem>
            <ToolbarItem>
              <Button variant="secondary" onClick={handleReload} isDisabled={reloading}>
                {reloading ? 'Reloading...' : 'Reload BIND'}
              </Button>
            </ToolbarItem>
            {bindStatus && (
              <ToolbarItem alignSelf="center">
                <span style={{ fontSize: '0.875rem', color: '#6a6e73' }}>
                  {!bindStatus.running
                    ? 'named is not running'
                    : !bindStatus.configValid
                      ? 'named is running, but named.conf has errors'
                      : bindStatus.rndc
                        ? 'named is running'
                        : 'named is running (rndc unavailable, using systemctl)'}
                </span>
              </ToolbarItem>
            )}
          </ToolbarContent>
        </Toolbar>
        {notice && (
          <Alert
            variant={notice.variant}
            isInline
            title={notice.text}
            style={{ marginTop: '1rem' }}
            actionClose={<Button variant="plain" onClick={() => setNotice(null)}>&times;</Button>}
          />
        )}
      </div>

      {/* Configured DNS Zones Table */}
      <table className="pf-v6-c-table pf-m-compact" role="grid" aria-label="Configured DNS Zones">
        <thead>
          <tr role="row">
            <th role="columnheader" scope="col">Zone</th>
            <th role="columnheader" scope="col">Type</th>
            <th role="columnheader" scope="col"></th>
          </tr>
        </thead>
        <tbody role="rowgroup">
          {zones.map((zone, index) => (
            <tr key={index} role="row">
              <td role="cell" data-label="Zone">{zone.name}</td>
              <td role="cell" data-label="Type">{zone.type}</td>
              <td role="cell" className="pf-v6-c-table__action">
                <Button
                  variant="secondary"
                  onClick={() => handleEditZone(zone)}
                  style={{ marginRight: '0.5rem' }}
                >
                  Edit
                </Button>
                <Button
                  variant="danger"
                  onClick={() => handleDeleteZone(zone.name)}
                >
                  Delete
                </Button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {/* Add New Zone Modal */}
      {isConfOpen && (
        <NamedConfEditor
          onClose={() => setIsConfOpen(false)}
          onSaved={() => { loadZones(); loadBindStatus(); }}
        />
      )}

      <ZoneImportModal
        isOpen={isImportOpen}
        onClose={() => setIsImportOpen(false)}
        onImported={() => { loadZones(); loadBindStatus(); }}
      />

      <Modal
        variant={ModalVariant.medium}
        title="Add New Zone"
        isOpen={isModalOpen}
        onClose={handleModalToggle}
      >
        <ModalBody>
          <Form>
            <FormGroup label="Zone Name" isRequired fieldId="zone-name">
              <TextInput
                isRequired
                type="text"
                id="zone-name"
                name="zone-name"
                value={newZoneName}
                onChange={(event, value) => setNewZoneName(value)}
                placeholder="example.com"
              />
            </FormGroup>

            <FormGroup label="Build a reverse zone name from a network" fieldId="zone-network">
              <TextInput
                type="text"
                id="zone-network"
                name="zone-network"
                value={newZoneNetwork}
                onChange={(event, value) => setNewZoneNetwork(value)}
                placeholder="192.168.1.0/24"
              />
              <p style={{ fontSize: '0.875rem', color: '#6a6e73', marginTop: '0.25rem' }}>
                Optional. Works out the in-addr.arpa or ip6.arpa name for you.
              </p>
              {reverseHint && reverseHint.error && (
                <p style={{ fontSize: '0.875rem', color: '#c9190b', marginTop: '0.5rem' }}>
                  {reverseHint.error}
                </p>
              )}
              {reverseHint && reverseHint.zones && (
                <div style={{ marginTop: '0.5rem' }}>
                  {reverseHint.zones.map((z) => (
                    <div key={z} style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.25rem' }}>
                      <code style={{ fontSize: '0.875rem' }}>{z}</code>
                      <Button variant="link" isInline onClick={() => setNewZoneName(z)}>
                        Use this name
                      </Button>
                    </div>
                  ))}
                  {reverseHint.note && (
                    <p style={{ fontSize: '0.875rem', color: '#6a6e73', marginTop: '0.25rem' }}>
                      {reverseHint.note}
                    </p>
                  )}
                </div>
              )}
            </FormGroup>

            <FormGroup label="Type" isRequired fieldId="zone-type">
              <select
                id="zone-type"
                value={newZoneType}
                onChange={(e) => setNewZoneType(e.target.value)}
                className="pf-v6-c-form-control"
              >
                <option value="Primary">Primary</option>
                <option value="Secondary">Secondary</option>
                <option value="Forward">Forward</option>
              </select>
            </FormGroup>

            {newZoneType === 'Primary' && (
              <>
                <FormGroup label="Primary Name Server" isRequired fieldId="zone-primary">
                  <TextInput
                    isRequired
                    type="text"
                    id="zone-primary"
                    name="zone-primary"
                    value={newZonePrimary}
                    onChange={(event, value) => setNewZonePrimary(value)}
                    placeholder="ns1.example.com."
                  />
                  <p style={{ fontSize: '0.875rem', color: '#6a6e73', marginTop: '0.25rem' }}>
                    Authoritative name server for this zone. Use a fully qualified name
                    ending in a dot; this host also needs an A or AAAA record in the zone
                    or named will refuse to load it.
                  </p>
                </FormGroup>

                <FormGroup label="Contact Email" isRequired fieldId="zone-contact">
                  <TextInput
                    isRequired
                    type="text"
                    id="zone-contact"
                    name="zone-contact"
                    value={newZoneContact}
                    onChange={(event, value) => setNewZoneContact(value)}
                    placeholder="admin.example.com."
                  />
                  <p style={{ fontSize: '0.875rem', color: '#6a6e73', marginTop: '0.25rem' }}>
                    Email in DNS format (use . instead of @)
                  </p>
                </FormGroup>
              </>
            )}

            {newZoneType === 'Secondary' && (
              <FormGroup label="Primary Servers" isRequired fieldId="zone-primaries">
                <TextInput
                  isRequired
                  type="text"
                  id="zone-primaries"
                  name="zone-primaries"
                  value={newZonePrimaries}
                  onChange={(event, value) => setNewZonePrimaries(value)}
                  placeholder="192.168.1.10, 192.168.1.11"
                />
                <p style={{ fontSize: '0.875rem', color: '#6a6e73', marginTop: '0.25rem' }}>
                  Addresses to transfer this zone from. The SOA and records come from the
                  transfer, so there is nothing to fill in here.
                </p>
              </FormGroup>
            )}

            {newZoneType === 'Forward' && (
              <FormGroup label="Forwarders" isRequired fieldId="zone-forwarders">
                <TextInput
                  isRequired
                  type="text"
                  id="zone-forwarders"
                  name="zone-forwarders"
                  value={newZoneForwarders}
                  onChange={(event, value) => setNewZoneForwarders(value)}
                  placeholder="10.0.0.53, 10.0.0.54"
                />
                <p style={{ fontSize: '0.875rem', color: '#6a6e73', marginTop: '0.25rem' }}>
                  Queries for this zone are sent to these servers. No zone data is held locally.
                </p>
              </FormGroup>
            )}

          </Form>
        </ModalBody>
        <ModalFooter>
          <Button variant="primary" onClick={handleAddZone}>
            Add
          </Button>
          <Button variant="link" onClick={handleModalToggle}>
            Cancel
          </Button>
        </ModalFooter>
      </Modal>
    </PageSection>
  );
};
