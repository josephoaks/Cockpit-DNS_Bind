import React, { useEffect, useState } from 'react';
import {
  Breadcrumb,
  BreadcrumbItem,
  Button,
  Checkbox,
  PageSection,
  Spinner,
  Alert,
  Tabs,
  Tab,
  TabTitleText,
  Toolbar,
  ToolbarContent,
  ToolbarItem,
  Modal,
  ModalBody,
  ModalFooter,
  ModalVariant,
  Form,
  FormGroup,
  TextInput,
} from '@patternfly/react-core';
import { PlusIcon } from '@patternfly/react-icons';
import { spawnBackend, reloadNotice, spawnTsigBackend } from '../utils/backend';
import { TimeInput } from './TimeInput';

export const ZoneEditorPage = ({ zone, onBack }) => {
  const [activeTabKey, setActiveTabKey] = useState(0);
  const [zoneData, setZoneData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  // Modal state for A/AAAA/CNAME records
  const [isRecordModalOpen, setIsRecordModalOpen] = useState(false);
  const [editingRecord, setEditingRecord] = useState(null);
  const [recordName, setRecordName] = useState('');
  const [recordType, setRecordType] = useState('A');
  const [recordValue, setRecordValue] = useState('');
  const [createPtr, setCreatePtr] = useState(true);

  // Records table sorting
  const [recordSortField, setRecordSortField] = useState('name');
  const [recordSortDir, setRecordSortDir] = useState('asc');

  // Basics tab state
  const [allowDynamicUpdates, setAllowDynamicUpdates] = useState(false);
  const [tsigKey, setTsigKey] = useState('');
  const [enableZoneTransport, setEnableZoneTransport] = useState(false);
  const [aclAny, setAclAny] = useState(true);
  const [aclLocalhost, setAclLocalhost] = useState(false);
  const [aclLocalnets, setAclLocalnets] = useState(false);
  const [tsigKeys, setTsigKeys] = useState([]);

  // Inline MX record state
  const [mxAddress, setMxAddress] = useState('');
  const [mxPriority, setMxPriority] = useState('0');

  // Inline NS record state
  const [nsNameserver, setNsNameserver] = useState('');

  // SOA form state
  const [refreshValue, setRefreshValue] = useState('3');
  const [refreshUnit, setRefreshUnit] = useState('h');
  const [retryValue, setRetryValue] = useState('1');
  const [retryUnit, setRetryUnit] = useState('h');
  const [expiryValue, setExpiryValue] = useState('1');
  const [expiryUnit, setExpiryUnit] = useState('w');
  const [minimumValue, setMinimumValue] = useState('1');
  const [minimumUnit, setMinimumUnit] = useState('d');
  const [ttlValue, setTtlValue] = useState('2');
  const [ttlUnit, setTtlUnit] = useState('d');

  useEffect(() => {
    loadZoneDetails();
    loadTsigKeys();
  }, [zone.name]);

  const parseTimeValue = (timeStr) => {
    if (!timeStr) return { value: '0', unit: 's' };
    const match = timeStr.match(/^(\d+)([smhdw]?)$/);
    if (match) {
      return { value: match[1], unit: match[2] || 's' };
    }
    return { value: timeStr, unit: 's' };
  };

  const loadZoneDetails = async () => {
    try {
      setLoading(true);
      setError(null);
      const output = await spawnBackend(['get', zone.name]);
      const data = JSON.parse(output);
      setZoneData(data);

      if (data.soa) {
        const refresh = parseTimeValue(data.soa.refresh);
        setRefreshValue(refresh.value);
        setRefreshUnit(refresh.unit);

        const retry = parseTimeValue(data.soa.retry);
        setRetryValue(retry.value);
        setRetryUnit(retry.unit);

        const expiry = parseTimeValue(data.soa.expiry);
        setExpiryValue(expiry.value);
        setExpiryUnit(expiry.unit);

        const minimum = parseTimeValue(data.soa.minimum);
        setMinimumValue(minimum.value);
        setMinimumUnit(minimum.unit);
      }

      if (data.ttl) {
        const ttl = parseTimeValue(data.ttl);
        setTtlValue(ttl.value);
        setTtlUnit(ttl.unit);
      }

      setLoading(false);
    } catch (err) {
      console.error('Failed to load zone details:', err);
      setError('Failed to load zone details: ' + err.message);
      setLoading(false);
    }
  };

  const loadTsigKeys = async () => {
    try {
      const output = await spawnTsigBackend(['list']);
      const result = JSON.parse(output);

      if (result.error) {
        console.error('Failed to load TSIG keys:', result.error);
        setTsigKeys([]);
      } else {
        setTsigKeys(result.keys || []);
      }
    } catch (err) {
      console.error('Failed to load TSIG keys:', err);
      setTsigKeys([]);
    }
  };

  const handleTabClick = (event, tabIndex) => {
    setActiveTabKey(tabIndex);
  };

  // Records table sorting helpers
  const toggleRecordSort = (field) => {
    if (recordSortField === field) {
      setRecordSortDir(recordSortDir === 'asc' ? 'desc' : 'asc');
    } else {
      setRecordSortField(field);
      setRecordSortDir('asc');
    }
  };
  const recordSortIndicator = (field) =>
    recordSortField === field ? (recordSortDir === 'asc' ? ' \u25B2' : ' \u25BC') : '';
  const recordAriaSort = (field) =>
    recordSortField === field ? (recordSortDir === 'asc' ? 'ascending' : 'descending') : 'none';

  // A/AAAA/CNAME Record handlers
  const handleAddRecord = () => {
    setEditingRecord(null);
    setRecordName('');
    setRecordType('A');
    setRecordValue('');
    setCreatePtr(true);
    setIsRecordModalOpen(true);
  };

  const handleEditRecord = (record) => {
    setEditingRecord(record);
    setRecordName(record.name);
    setRecordType(record.type);
    setRecordValue(record.value);
    setIsRecordModalOpen(true);
  };

  // Any write returns a `reload` block; surface it when it did not apply
  // cleanly, plus any validation warning the backend attached.
  const noteWriteResult = (result) => {
    const notice = reloadNotice(result);
    if (result && result.warning) {
      setError(result.warning);
    } else if (notice) {
      setError(notice.text);
    } else {
      setError(null);
    }
  };

  // A PTR was skipped only because its reverse zone does not exist yet. We know
  // the address and the name, so the zone name is derivable -- offer to create
  // it rather than sending the user off to build it by hand.
  const offerReverseZone = async (ptr, recName, recValue) => {
    if (!ptr || ptr.status !== 'skipped' || !ptr.needed) return false;
    if (!confirm(`${ptr.message}\n\nCreate ${ptr.needed} now and add the PTR?\n\n`
      + `It will be created as a primary zone using the same name server and `
      + `contact as ${zone.name}.`)) return false;

    const out = await spawnBackend(['add-ptr', JSON.stringify({
      zone: zone.name, name: recName, value: recValue, createReverseZone: true
    })]);
    const res = JSON.parse(out);
    if (res.error) {
      setError('Failed to create reverse zone: ' + res.error);
      return false;
    }
    if (res.ptr && res.ptr.status !== 'created') {
      setError(res.ptr.message);
      return false;
    }
    return true;
  };

  const handleCreatePtr = async (record) => {
    try {
      const output = await spawnBackend(['add-ptr', JSON.stringify({
        zone: zone.name, name: record.name, value: record.value
      })]);
      const result = JSON.parse(output);

      if (result.error) {
        setError('Failed to create PTR: ' + result.error);
        return;
      }

      const ptr = result.ptr || {};
      // A second PTR on one address is a deliberate choice, not a default.
      if (ptr.status === 'conflict') {
        if (!confirm(ptr.message + '\n\nAdd the second PTR anyway?')) return;
        const forced = await spawnBackend(['add-ptr', JSON.stringify({
          zone: zone.name, name: record.name, value: record.value, force: true
        })]);
        const forcedResult = JSON.parse(forced);
        if (forcedResult.error) {
          setError('Failed to create PTR: ' + forcedResult.error);
          return;
        }
      } else if (ptr.status === 'skipped' && ptr.needed) {
        if (!await offerReverseZone(ptr, record.name, record.value)) return;
      } else if (ptr.status !== 'created') {
        alert(ptr.message);
        return;
      }

      noteWriteResult(result);
      await loadZoneDetails();
    } catch (err) {
      console.error('Failed to create PTR:', err);
      setError('Failed to create PTR: ' + err.message);
    }
  };

  const handleDeleteRecord = async (record) => {
    if (!confirm(`Delete ${record.type} record ${record.name}?`)) return;

    // Only address records have a reverse counterpart worth cleaning up.
    let deleteReverse = false;
    if (record.type === 'A' || record.type === 'AAAA') {
      deleteReverse = confirm(
        `Also remove the matching PTR record for ${record.value}?\n\n` +
        `Only a PTR pointing back at ${record.name} is removed; other names ` +
        `sharing this address keep theirs.`
      );
    }

    try {
      const data = {
        zone: zone.name,
        name: record.name,
        type: record.type,
        value: record.value,
        deleteReverse
      };
      const output = await spawnBackend(['delete-record', JSON.stringify(data)]);
      const result = JSON.parse(output);

      if (result.error) {
        setError('Failed to delete record: ' + result.error);
        return;
      }

      if (result.ptr && result.ptr.status === 'skipped') {
        alert(result.ptr.message);
      }

      noteWriteResult(result);
      await loadZoneDetails();
    } catch (err) {
      console.error('Failed to delete record:', err);
      setError('Failed to delete record: ' + err.message);
    }
  };

  const handleSaveRecord = async () => {
    if (!recordName.trim() || !recordValue.trim()) {
      alert('Please fill in all fields');
      return;
    }

    try {
      if (editingRecord) {
        const data = {
          zone: zone.name,
          oldName: editingRecord.name,
          oldValue: editingRecord.value,
          name: recordName,
          type: recordType,
          value: recordValue
        };
        const output = await spawnBackend(['update-record', JSON.stringify(data)]);
        const result = JSON.parse(output);

        if (result.error) {
          setError('Failed to update record: ' + result.error);
          return;
        }
      } else {
        const data = {
          zone: zone.name,
          name: recordName,
          type: recordType,
          value: recordValue,
          createReverse: (recordType === 'A' || recordType === 'AAAA') ? createPtr : false
        };
        const output = await spawnBackend(['add-record', JSON.stringify(data)]);
        const result = JSON.parse(output);

        if (result.error) {
          setError('Failed to add record: ' + result.error);
          return;
        }
        // Reverse (PTR) was requested but couldn't be created cleanly.
        if (result.ptr && result.ptr.status === 'conflict') {
          // One PTR per address is the recommended setup; make the user opt in.
          if (confirm(result.ptr.message + '\n\nAdd the second PTR anyway?')) {
            const forced = await spawnBackend(['add-ptr', JSON.stringify({
              zone: zone.name, name: recordName, value: recordValue, force: true
            })]);
            const forcedResult = JSON.parse(forced);
            if (forcedResult.error) {
              setError('Failed to create PTR: ' + forcedResult.error);
            }
          }
        } else if (result.ptr && result.ptr.status === 'skipped' && result.ptr.needed) {
          await offerReverseZone(result.ptr, recordName, recordValue);
        } else if (result.ptr && result.ptr.status !== 'created') {
          alert(result.ptr.message);
        }
        noteWriteResult(result);
      }

      await loadZoneDetails();
      setIsRecordModalOpen(false);
    } catch (err) {
      console.error('Failed to save record:', err);
      setError('Failed to save record: ' + err.message);
    }
  };

  const handleCloseRecordModal = () => {
    setIsRecordModalOpen(false);
    setEditingRecord(null);
  };

  const handleSaveBasics = async () => {
    // Validate TSIG key if dynamic updates enabled
    if (allowDynamicUpdates && !tsigKey) {
      setError('Error: No TSIG key is defined');
      return;
    }

    try {
      const acls = [];
      if (aclAny) acls.push('any');
      if (aclLocalhost) acls.push('localhost');
      if (aclLocalnets) acls.push('localnets');

      const basicsData = {
        zone: zone.name,
        allowDynamicUpdates,
        tsigKey,
        enableZoneTransport,
        acls
      };

      const output = await spawnBackend(['update-zone-options', JSON.stringify(basicsData)]);
      const result = JSON.parse(output);

      if (result.error) {
        setError('Failed to save zone options: ' + result.error);
        return;
      }

      alert('Zone options saved successfully');
    } catch (err) {
      console.error('Failed to save basics:', err);
      setError('Failed to save zone options: ' + err.message);
    }
  };

  const handleClearBasics = async () => {
    if (!confirm('Clear all dynamic update and zone transfer settings for this zone?')) return;

    try {
      const basicsData = {
        zone: zone.name,
        allowDynamicUpdates: false,
        tsigKey: '',
        enableZoneTransport: false,
        acls: []
      };

      const output = await spawnBackend(['update-zone-options', JSON.stringify(basicsData)]);
      const result = JSON.parse(output);

      if (result.error) {
        setError('Failed to clear zone options: ' + result.error);
        return;
      }

      // Reset UI state
      setAllowDynamicUpdates(false);
      setTsigKey('');
      setEnableZoneTransport(false);
      setAclAny(true);
      setAclLocalhost(false);
      setAclLocalnets(false);

      alert('Zone options cleared successfully');
    } catch (err) {
      console.error('Failed to clear basics:', err);
      setError('Failed to clear zone options: ' + err.message);
    }
  };

  const handleGenerateKey = async () => {
    if (!newKeyName.trim()) {
      setError('Please enter a key name');
      return;
    }

    try {
      const output = await spawnBackend(['generate-tsig-key', JSON.stringify({
        name: newKeyName.trim(),
        algorithm: newKeyAlgorithm
      })]);
      const result = JSON.parse(output);

      if (result.error) {
        setError('Failed to generate TSIG key: ' + result.error);
        return;
      }

      alert(`TSIG key "${newKeyName}" created successfully`);

      // Reload keys
      const keysOutput = await spawnBackend(['list-tsig-keys']);
      const keys = JSON.parse(keysOutput);
      setTsigKeys(keys);

      // Auto-select the new key and collapse form
      setTsigKey(newKeyName);
      setShowCreateKey(false);
      setNewKeyName('');
      setNewKeyAlgorithm('hmac-sha256');
    } catch (err) {
      console.error('Failed to create TSIG key:', err);
      setError('Failed to create TSIG key: ' + err.message);
    }
  };


  // NS Record handlers
  const handleAddNsRecord = async () => {
    if (!nsNameserver.trim()) {
      alert('Please enter a name server');
      return;
    }

    try {
      const data = {
        zone: zone.name,
        name: zone.name + '.',
        nameserver: nsNameserver.trim()
      };

      const output = await spawnBackend(['add-ns-record', JSON.stringify(data)]);
      const result = JSON.parse(output);

      if (result.error) {
        setError('Failed to add NS record: ' + result.error);
        return;
      }

      setNsNameserver('');
      await loadZoneDetails();
    } catch (err) {
      console.error('Failed to add NS record:', err);
      setError('Failed to add NS record: ' + err.message);
    }
  };

  const handleDeleteNsRecord = async (record) => {
    if (!confirm(`Delete NS record ${record.nameserver}?`)) return;

    try {
      const data = {
        zone: zone.name,
        name: record.name,
        nameserver: record.nameserver
      };

      const output = await spawnBackend(['delete-ns-record', JSON.stringify(data)]);
      const result = JSON.parse(output);

      if (result.error) {
        setError('Failed to delete NS record: ' + result.error);
        return;
      }

      await loadZoneDetails();
    } catch (err) {
      console.error('Failed to delete NS record:', err);
      setError('Failed to delete NS record: ' + err.message);
    }
  };

  // MX Record handlers
  const handleAddMxRecord = async () => {
    if (!mxAddress.trim()) {
      alert('Please enter a mail server address');
      return;
    }

    try {
      const data = {
        zone: zone.name,
        name: '@',
        priority: parseInt(mxPriority) || 0,
        mailserver: mxAddress.trim()
      };

      const output = await spawnBackend(['add-mx-record', JSON.stringify(data)]);
      const result = JSON.parse(output);

      if (result.error) {
        setError('Failed to add MX record: ' + result.error);
        return;
      }

      setMxAddress('');
      setMxPriority('0');
      await loadZoneDetails();
    } catch (err) {
      console.error('Failed to add MX record:', err);
      setError('Failed to add MX record: ' + err.message);
    }
  };

  const handleDeleteMxRecord = async (record) => {
    if (!confirm(`Delete MX record ${record.mailserver}?`)) return;

    try {
      const data = {
        zone: zone.name,
        name: record.name,
        mailserver: record.mailserver
      };

      const output = await spawnBackend(['delete-mx-record', JSON.stringify(data)]);
      const result = JSON.parse(output);

      if (result.error) {
        setError('Failed to delete MX record: ' + result.error);
        return;
      }

      await loadZoneDetails();
    } catch (err) {
      console.error('Failed to delete MX record:', err);
      setError('Failed to delete MX record: ' + err.message);
    }
  };

  // SOA handler
  const handleSaveSOA = async () => {
    try {
      const soaData = {
        zone: zone.name,
        primary: zoneData.soa.primary,
        contact: zoneData.soa.contact,
        serial: zoneData.soa.serial,
        refresh: `${refreshValue}${refreshUnit}`,
        retry: `${retryValue}${retryUnit}`,
        expiry: `${expiryValue}${expiryUnit}`,
        minimum: `${minimumValue}${minimumUnit}`,
        ttl: `${ttlValue}${ttlUnit}`
      };

      const output = await spawnBackend(['update-soa', JSON.stringify(soaData)]);
      const result = JSON.parse(output);

      if (result.error) {
        setError('Failed to update SOA: ' + result.error);
        return;
      }

      alert('SOA record updated successfully');
      await loadZoneDetails();
    } catch (err) {
      console.error('Failed to save SOA:', err);
      setError('Failed to save SOA: ' + err.message);
    }
  };

  if (loading) {
    return (
      <PageSection padding={{ default: 'padding' }}>
        <Spinner size="xl" />
      </PageSection>
    );
  }

  return (
    <PageSection padding={{ default: 'padding' }}>
      <Breadcrumb style={{ marginBottom: '1.5rem' }}>
        <BreadcrumbItem>
          <Button variant="link" onClick={onBack} style={{ padding: 0 }}>
            DNS Zones
          </Button>
        </BreadcrumbItem>
        <BreadcrumbItem isActive>{zone.name}</BreadcrumbItem>
      </Breadcrumb>

      {error && (
        <Alert
          variant="danger"
          title={error}
          isInline
          actionClose={<Button variant="plain" onClick={() => setError(null)}>×</Button>}
          style={{ marginBottom: '1rem' }}
        />
      )}

      <h1 style={{ marginBottom: '1.5rem' }}>Zone Editor</h1>
      <h2 style={{ marginBottom: '1.5rem', fontSize: '1.2rem' }}>
        Settings for Zone {zone.name}
      </h2>

      <Tabs activeKey={activeTabKey} onSelect={handleTabClick}>
        <Tab eventKey={0} title={<TabTitleText>Basics</TabTitleText>}>
          <div style={{ padding: '1.5rem' }}>
            <h3 style={{ marginBottom: '1.5rem' }}>Basics</h3>

            <Form>
              {/* Allow Dynamic Updates */}
              <FormGroup fieldId="allow-dynamic-updates" style={{ marginBottom: '1.5rem' }}>
                <Checkbox
                  id="allow-dynamic-updates"
                  label="Allow Dynamic Updates"
                  isChecked={allowDynamicUpdates}
                  onChange={(event, checked) => setAllowDynamicUpdates(checked)}
                />
              </FormGroup>

	      {/* TSIG Key */}
              <FormGroup label="TSIG Key" fieldId="tsig-key" style={{ marginBottom: '2rem', maxWidth: '500px' }}>
                <select
                  id="tsig-key"
                  value={tsigKey}
                  onChange={(e) => setTsigKey(e.target.value)}
                  className="pf-v6-c-form-control"
                  disabled={!allowDynamicUpdates || tsigKeys.length === 0}
                >
                  <option value="">-- Select TSIG Key --</option>
                  {tsigKeys.map((key, idx) => (
                    <option key={idx} value={key.name}>{key.name}</option>
                  ))}
                </select>

                {/* TSIG Key Management Link */}
                <div style={{ marginTop: '1rem' }}>
                  <Button 
                    variant="link" 
                    isInline
                    onClick={() => {
                      window.dispatchEvent(new CustomEvent('navigate-to-tab', { detail: { tabIndex: 4 } }));
                    }}
                    isDisabled={!allowDynamicUpdates}
                  >
                    Create TSIG Key
                  </Button>
                </div>

              </FormGroup>

              {/* Enable Zone Transport */}
              <FormGroup fieldId="enable-zone-transport" style={{ marginBottom: '1rem' }}>
                <Checkbox
                  id="enable-zone-transport"
                  label="Enable Zone Transport"
                  isChecked={enableZoneTransport}
                  onChange={(event, checked) => setEnableZoneTransport(checked)}
                />
              </FormGroup>
        
              {/* ACLs */}
              {enableZoneTransport && (
                <FormGroup label="ACLs" fieldId="acls" style={{ marginLeft: '2rem', marginBottom: '2rem' }}>
                  <Checkbox
                    id="acl-any"
                    label="any"
                    isChecked={aclAny}
                    onChange={(event, checked) => setAclAny(checked)}
                    style={{ marginBottom: '0.5rem' }}
                  />
                  <Checkbox
                    id="acl-localhost"
                    label="localhost"
                    isChecked={aclLocalhost}
                    onChange={(event, checked) => setAclLocalhost(checked)}
                    style={{ marginBottom: '0.5rem' }}
                  />
                  <Checkbox
                    id="acl-localnets"
                    label="localnets"
                    isChecked={aclLocalnets}
                    onChange={(event, checked) => setAclLocalnets(checked)}
                  />
                </FormGroup>
              )}

              <div style={{ display: 'flex', gap: '1rem' }}>
                <Button variant="primary" onClick={handleSaveBasics} style={{ maxWidth: '200px' }}>
                  Save Changes
                </Button>
                {(allowDynamicUpdates || enableZoneTransport) && (
                  <Button variant="danger" onClick={handleClearBasics} style={{ maxWidth: '200px' }}>
                    Clear Settings
                  </Button>
                )}
              </div>
            </Form>
          </div>
        </Tab>

        <Tab eventKey={1} title={<TabTitleText>NS Records</TabTitleText>}>
          <div style={{ padding: '1.5rem' }}>
            <h3 style={{ marginBottom: '1.5rem' }}>NS Records</h3>

            <div style={{ marginBottom: '2rem' }}>
              <div style={{ display: 'flex', gap: '1rem', alignItems: 'end', maxWidth: '600px' }}>
                <FormGroup label="Name Server" fieldId="ns-nameserver" style={{ flex: 1 }}>
                  <TextInput
                    type="text"
                    id="ns-nameserver"
                    value={nsNameserver}
                    onChange={(event, value) => setNsNameserver(value)}
                    placeholder="ns1.example.com."
                  />
                </FormGroup>
                <div style={{ paddingBottom: '0.25rem' }}>
                  <Button variant="primary" onClick={handleAddNsRecord}>Add</Button>
                </div>
              </div>
            </div>

            <div>
              <table className="pf-v6-c-table pf-m-compact" role="grid">
                <thead>
                  <tr role="row">
                    <th role="columnheader" scope="col">Name Server</th>
                    <th role="columnheader" scope="col"></th>
                  </tr>
                </thead>
                <tbody role="rowgroup">
                  {zoneData?.ns_records && zoneData.ns_records.length > 0 ? (
                    zoneData.ns_records.map((record, idx) => (
                      <tr key={idx} role="row">
                        <td role="cell">{record.nameserver}</td>
                        <td role="cell" className="pf-v6-c-table__action">
                          <Button variant="danger" onClick={() => handleDeleteNsRecord(record)}>
                            Delete
                          </Button>
                        </td>
                      </tr>
                    ))
                  ) : (
                    <tr role="row">
                      <td role="cell" colSpan="2" style={{ textAlign: 'center', fontStyle: 'italic' }}>
                        No NS records configured
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </Tab>

        <Tab eventKey={2} title={<TabTitleText>MX Records</TabTitleText>}>
          <div style={{ padding: '1.5rem' }}>
            <h3 style={{ marginBottom: '1.5rem' }}>MX Records</h3>

            <div style={{ marginBottom: '2rem' }}>
              <div style={{ display: 'flex', gap: '1rem', alignItems: 'end', maxWidth: '800px' }}>
                <FormGroup label="Address" fieldId="mx-address" style={{ flex: 1 }}>
                  <TextInput
                    type="text"
                    id="mx-address"
                    value={mxAddress}
                    onChange={(event, value) => setMxAddress(value)}
                    placeholder="mail.example.com"
                  />
                </FormGroup>
                <FormGroup label="Priority" fieldId="mx-priority" style={{ width: '150px' }}>
                  <TextInput
                    type="number"
                    id="mx-priority"
                    value={mxPriority}
                    onChange={(event, value) => setMxPriority(value)}
                  />
                </FormGroup>
                <div style={{ paddingBottom: '0.25rem' }}>
                  <Button variant="primary" onClick={handleAddMxRecord}>Add</Button>
                </div>
              </div>
            </div>

            <div>
              <table className="pf-v6-c-table pf-m-compact" role="grid">
                <thead>
                  <tr role="row">
                    <th role="columnheader" scope="col">Mail Server</th>
                    <th role="columnheader" scope="col">Priority</th>
                    <th role="columnheader" scope="col"></th>
                  </tr>
                </thead>
                <tbody role="rowgroup">
                  {zoneData?.mx_records && zoneData.mx_records.length > 0 ? (
                    zoneData.mx_records.map((record, idx) => (
                      <tr key={idx} role="row">
                        <td role="cell">{record.mailserver}</td>
                        <td role="cell">{record.priority}</td>
                        <td role="cell" className="pf-v6-c-table__action">
                          <Button variant="danger" onClick={() => handleDeleteMxRecord(record)}>
                            Delete
                          </Button>
                        </td>
                      </tr>
                    ))
                  ) : (
                    <tr role="row">
                      <td role="cell" colSpan="3" style={{ textAlign: 'center', fontStyle: 'italic' }}>
                        No MX records configured
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </Tab>

        <Tab eventKey={3} title={<TabTitleText>SOA</TabTitleText>}>
          <div style={{ padding: '1.5rem' }}>
            <h3 style={{ marginBottom: '1rem' }}>Start of Authority (SOA)</h3>

            {zoneData?.soa && (
              <Form>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem', maxWidth: '900px' }}>
                  <div>
                    <FormGroup label="Serial" fieldId="soa-serial" style={{ marginBottom: '1rem' }}>
                      <TextInput type="text" id="soa-serial" value={zoneData.soa.serial} readOnly />
                      <p style={{ fontSize: '0.875rem', color: '#6a6e73', marginTop: '0.25rem' }}>
                        Auto-incremented when zone is modified
                      </p>
                    </FormGroup>

                    <FormGroup label="TTL" fieldId="zone-ttl" style={{ marginBottom: '1rem' }}>
                      <TimeInput
                        id="zone-ttl"
                        value={ttlValue}
                        unit={ttlUnit}
                        onValueChange={(e, val) => setTtlValue(val)}
                        onUnitChange={(e) => setTtlUnit(e.target.value)}
                      />
                      <p style={{ fontSize: '0.875rem', color: '#6a6e73', marginTop: '0.25rem' }}>
                        Default time-to-live for records
                      </p>
                    </FormGroup>
                  </div>

                  <div>
                    <FormGroup label="Refresh" fieldId="soa-refresh" style={{ marginBottom: '1rem' }}>
                      <TimeInput
                        id="soa-refresh"
                        value={refreshValue}
                        unit={refreshUnit}
                        onValueChange={(e, val) => setRefreshValue(val)}
                        onUnitChange={(e) => setRefreshUnit(e.target.value)}
                      />
                      <p style={{ fontSize: '0.875rem', color: '#6a6e73', marginTop: '0.25rem' }}>
                        How often secondary servers check for updates
                      </p>
                    </FormGroup>

                    <FormGroup label="Retry" fieldId="soa-retry" style={{ marginBottom: '1rem' }}>
                      <TimeInput
                        id="soa-retry"
                        value={retryValue}
                        unit={retryUnit}
                        onValueChange={(e, val) => setRetryValue(val)}
                        onUnitChange={(e) => setRetryUnit(e.target.value)}
                      />
                      <p style={{ fontSize: '0.875rem', color: '#6a6e73', marginTop: '0.25rem' }}>
                        How long to wait before retrying a failed refresh
                      </p>
                    </FormGroup>

                    <FormGroup label="Expiration" fieldId="soa-expiry" style={{ marginBottom: '1rem' }}>
                      <TimeInput
                        id="soa-expiry"
                        value={expiryValue}
                        unit={expiryUnit}
                        onValueChange={(e, val) => setExpiryValue(val)}
                        onUnitChange={(e) => setExpiryUnit(e.target.value)}
                      />
                      <p style={{ fontSize: '0.875rem', color: '#6a6e73', marginTop: '0.25rem' }}>
                        How long secondary servers keep zone data without updates
                      </p>
                    </FormGroup>

                    <FormGroup label="Minimum" fieldId="soa-minimum" style={{ marginBottom: '1rem' }}>
                      <TimeInput
                        id="soa-minimum"
                        value={minimumValue}
                        unit={minimumUnit}
                        onValueChange={(e, val) => setMinimumValue(val)}
                        onUnitChange={(e) => setMinimumUnit(e.target.value)}
                      />
                      <p style={{ fontSize: '0.875rem', color: '#6a6e73', marginTop: '0.25rem' }}>
                        Negative caching TTL
                      </p>
                    </FormGroup>
                  </div>
                </div>

                <div style={{ marginTop: '2rem' }}>
                  <Button variant="primary" onClick={handleSaveSOA}>Save Changes</Button>
                </div>
              </Form>
            )}
          </div>
        </Tab>

        <Tab eventKey={4} title={<TabTitleText>Records</TabTitleText>}>
          <div style={{ padding: '1.5rem' }}>
            <h3>Records</h3>
            <p style={{ marginBottom: '1rem' }}>DNS records (A, AAAA, CNAME, etc.)</p>

            <Toolbar style={{ marginBottom: '1.5rem' }}>
              <ToolbarContent>
                <ToolbarItem>
                  <Button variant="primary" icon={<PlusIcon />} onClick={handleAddRecord}>
                    Add
                  </Button>
                </ToolbarItem>
              </ToolbarContent>
            </Toolbar>

	  {zoneData?.records && (
              <div style={{ maxHeight: 'calc(100vh - 22rem)', overflow: 'auto' }}>
              <table className="pf-v6-c-table pf-m-compact pf-m-sticky-header" role="grid">
                <thead>
                  <tr role="row">
                    <th role="columnheader" scope="col" aria-sort={recordAriaSort('name')}
                        style={{ cursor: 'pointer', userSelect: 'none' }}
                        onClick={() => toggleRecordSort('name')}>
                      Record Key{recordSortIndicator('name')}
                    </th>
                    <th role="columnheader" scope="col" aria-sort={recordAriaSort('type')}
                        style={{ cursor: 'pointer', userSelect: 'none' }}
                        onClick={() => toggleRecordSort('type')}>
                      Type{recordSortIndicator('type')}
                    </th>
                    <th role="columnheader" scope="col" aria-sort={recordAriaSort('value')}
                        style={{ cursor: 'pointer', userSelect: 'none' }}
                        onClick={() => toggleRecordSort('value')}>
                      Value{recordSortIndicator('value')}
                    </th>
                    <th role="columnheader" scope="col"></th>
                  </tr>
                </thead>
                <tbody role="rowgroup">
                  {[...zoneData.records].sort((a, b) => {
                    const dir = recordSortDir === 'asc' ? 1 : -1;
                    const av = (a[recordSortField] ?? '').toString();
                    const bv = (b[recordSortField] ?? '').toString();
                    return dir * av.localeCompare(bv, undefined, { numeric: true, sensitivity: 'base' });
                  }).map((record, idx) => (
                    <tr key={`${record.name}-${record.type}-${record.value}-${idx}`} role="row">
                      <td role="cell">{record.name}</td>
                      <td role="cell">{record.type}</td>
                      <td role="cell">{record.value}</td>
                      <td role="cell" className="pf-v6-c-table__action">
                        {(record.type === 'A' || record.type === 'AAAA') && (
                          <Button variant="secondary" onClick={() => handleCreatePtr(record)} style={{ marginRight: '0.5rem' }}>
                            Reverse
                          </Button>
                        )}
                        <Button variant="secondary" onClick={() => handleEditRecord(record)} style={{ marginRight: '0.5rem' }}>
                          Change
                        </Button>
                        <Button variant="danger" onClick={() => handleDeleteRecord(record)}>
                          Delete
                        </Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              </div>
            )}
          </div>
        </Tab>
      </Tabs>

      <Modal
        variant={ModalVariant.medium}
        title={editingRecord ? 'Edit Record' : 'Add Record'}
        isOpen={isRecordModalOpen}
        onClose={handleCloseRecordModal}
      >
        <ModalBody>
          <Form>
            <FormGroup label="Record Name" isRequired fieldId="record-name">
              <TextInput
                isRequired
                type="text"
                id="record-name"
                value={recordName}
                onChange={(event, value) => setRecordName(value)}
                placeholder="hostname"
              />
            </FormGroup>
            <FormGroup label="Type" isRequired fieldId="record-type">
              <select id="record-type" value={recordType} onChange={(e) => setRecordType(e.target.value)} className="pf-v6-c-form-control">
                <option value="A">A</option>
                <option value="AAAA">AAAA</option>
                <option value="CNAME">CNAME</option>
                <option value="TXT">TXT</option>
                <option value="PTR">PTR</option>
              </select>
            </FormGroup>
            <FormGroup label="Value" isRequired fieldId="record-value">
              <TextInput
                isRequired
                type="text"
                id="record-value"
                value={recordValue}
                onChange={(event, value) => setRecordValue(value)}
                placeholder="192.168.1.1"
              />
            </FormGroup>
            {!editingRecord && (recordType === 'A' || recordType === 'AAAA') && (
              <FormGroup fieldId="record-create-ptr">
                <Checkbox
                  id="record-create-ptr"
                  label="Also create reverse (PTR) record"
                  description="Adds a matching PTR in the hosted in-addr.arpa/ip6.arpa zone, if one exists. Skipped safely when no reverse zone is present or a PTR for this address already exists."
                  isChecked={createPtr}
                  onChange={(event, checked) => setCreatePtr(checked)}
                />
              </FormGroup>
            )}
          </Form>
        </ModalBody>
        <ModalFooter>
          <Button variant="primary" onClick={handleSaveRecord}>
            {editingRecord ? 'Save' : 'Add'}
          </Button>
          <Button variant="link" onClick={handleCloseRecordModal}>Cancel</Button>
        </ModalFooter>
      </Modal>
    </PageSection>
  );
};
