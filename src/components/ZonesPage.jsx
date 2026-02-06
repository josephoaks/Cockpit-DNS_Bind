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
import { spawnBackend } from '../utils/backend';
import { ZoneEditorPage } from './ZoneEditorPage';

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

  // Load zones on mount
  useEffect(() => {
    if (view === 'list') {
      loadZones();
    }
  }, [view]);

  const loadZones = async () => {
    try {
      setLoading(true);
      setError(null);
      const output = await spawnBackend(['list']);
      const allZones = JSON.parse(output);

      // Filter out system zones
      const userZones = allZones.filter(zone =>
        !zone.name.includes('localhost') &&
        !zone.name.includes('127.in-addr') &&
        !zone.name.includes('ip6.arpa') &&
        zone.name !== '.'
      );

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

  const handleAddZone = async () => {
    if (!newZoneName.trim() || !newZonePrimary.trim() || !newZoneContact.trim()) {
      alert('Please fill in all required fields');
      return;
    }

    try {
      const data = {
        name: newZoneName.trim(),
        type: newZoneType,
        primary: newZonePrimary.trim(),
        contact: newZoneContact.trim()
      };
      
      const output = await spawnBackend(['create-zone', JSON.stringify(data)]);
      const result = JSON.parse(output);
      
      if (result.error) {
        setError('Failed to create zone: ' + result.error);
        return;
      }
      
      // Reload zones list
      await loadZones();
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
          </ToolbarContent>
        </Toolbar>
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
                Authoritative name server for this zone
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
