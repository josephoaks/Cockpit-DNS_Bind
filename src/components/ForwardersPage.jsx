import React, { useEffect, useState } from 'react';
import {
  Button,
  PageSection,
  Spinner,
  Alert,
  Form,
  FormGroup,
  TextInput,
  Radio,
  Tooltip,
} from '@patternfly/react-core';
import { CheckCircleIcon } from '@patternfly/react-icons';
import { spawnForwardersBackend } from '../utils/backend';

export const ForwardersPage = () => {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [forwarders, setForwarders] = useState([]);
  const [policy, setPolicy] = useState('automatic');
  
  // Add forwarder state
  const [newForwarderIp, setNewForwarderIp] = useState('');
  const [validating, setValidating] = useState(false);

  const policyOptions = [
    { value: 'disabled', label: 'Merging forwarders is disabled', stigRecommended: false },
    { value: 'automatic', label: 'Automatic merging', stigRecommended: false },
    { value: 'enabled', label: 'Merging forwarders is enabled', stigRecommended: true },
    { value: 'custom', label: 'Custom configuration', stigRecommended: true },
  ];

  useEffect(() => {
    loadForwarders();
  }, []);

  const loadForwarders = async () => {
    try {
      setLoading(true);
      setError(null);
      const output = await spawnForwardersBackend(['list']);
      const result = JSON.parse(output);

      if (result.error) {
        setError(result.error);
        setForwarders([]);
        setPolicy('automatic');
      } else {
        setForwarders(result.forwarders || []);
        setPolicy(result.policy || 'automatic');
      }
      setLoading(false);
    } catch (err) {
      console.error('Failed to load forwarders:', err);
      setError('Failed to load forwarders: ' + err.message);
      setForwarders([]);
      setLoading(false);
    }
  };

  const validateIpFormat = (ip) => {
    // IPv4 regex
    const ipv4Regex = /^(\d{1,3}\.){3}\d{1,3}$/;
    // IPv6 regex (simplified)
    const ipv6Regex = /^([0-9a-fA-F]{0,4}:){2,7}[0-9a-fA-F]{0,4}$/;
    
    if (ipv4Regex.test(ip)) {
      // Validate each octet is 0-255
      const octets = ip.split('.');
      return octets.every(octet => {
        const num = parseInt(octet, 10);
        return num >= 0 && num <= 255;
      });
    }
    
    return ipv6Regex.test(ip);
  };

  const handleAddForwarder = async () => {
    const ip = newForwarderIp.trim();
    
    if (!ip) {
      alert('Please enter an IP address');
      return;
    }

    // Validate IP format
    if (!validateIpFormat(ip)) {
      setError('Invalid IP address format. Please enter a valid IPv4 or IPv6 address.');
      return;
    }

    // Check for duplicates
    if (forwarders.some(f => f.ip === ip)) {
      setError('This forwarder already exists');
      return;
    }

    try {
      setValidating(true);
      setError(null);

      const data = { ip };
      const output = await spawnForwardersBackend(['validate', JSON.stringify(data)]);
      const result = JSON.parse(output);

      if (result.error) {
        setError('Validation failed: ' + result.error);
        setValidating(false);
        return;
      }

      // REJECT if not a valid DNS server
      if (!result.validDns) {
        setError(`Cannot add ${ip}: Server does not respond to DNS queries. Only valid DNS servers can be added.`);
        setValidating(false);
        return;
      }

      // WARN if no DNSSEC but still allow
      if (!result.supportsDnssec) {
        if (!confirm(`Warning: ${ip} does not support DNSSEC validation.\n\nFor STIG compliance, DNSSEC-enabled servers are recommended.\n\nAdd anyway?`)) {
          setValidating(false);
          return;
        }
      }

      // Add the forwarder with validation results
      const addData = {
        ip,
        validDns: result.validDns,
        supportsDnssec: result.supportsDnssec
      };

      const addOutput = await spawnForwardersBackend(['add', JSON.stringify(addData)]);
      const addResult = JSON.parse(addOutput);

      if (addResult.error) {
        setError('Failed to add forwarder: ' + addResult.error);
        setValidating(false);
        return;
      }

      alert(`Forwarder ${ip} added successfully`);

      setNewForwarderIp('');
      setValidating(false);
      await loadForwarders();
    } catch (err) {
      console.error('Failed to add forwarder:', err);
      setError('Failed to add forwarder: ' + err.message);
      setValidating(false);
    }
  };

  const handleDeleteForwarder = async (ip) => {
    if (!confirm(`Delete forwarder ${ip}?`)) return;

    try {
      const data = { ip };
      const output = await spawnForwardersBackend(['delete', JSON.stringify(data)]);
      const result = JSON.parse(output);

      if (result.error) {
        setError('Failed to delete forwarder: ' + result.error);
        return;
      }

      await loadForwarders();
    } catch (err) {
      console.error('Failed to delete forwarder:', err);
      setError('Failed to delete forwarder: ' + err.message);
    }
  };

  const handleSavePolicy = async () => {
    try {
      const data = { policy };
      const output = await spawnForwardersBackend(['set-policy', JSON.stringify(data)]);
      const result = JSON.parse(output);

      if (result.error) {
        setError('Failed to save policy: ' + result.error);
        return;
      }

      alert('DNS resolution policy saved successfully');
    } catch (err) {
      console.error('Failed to save policy:', err);
      setError('Failed to save policy: ' + err.message);
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
      <h1 style={{ marginBottom: '1.5rem' }}>DNS Server: Forwarders</h1>

      {error && (
        <Alert
          variant="danger"
          title={error}
          isInline
          actionClose={<Button variant="plain" onClick={() => setError(null)}>×</Button>}
          style={{ marginBottom: '1rem' }}
        />
      )}

      {/* Local DNS Resolution Policy */}
      <div style={{ marginBottom: '2rem', padding: '1rem', border: '1px solid #ccc', borderRadius: '12px' }}>
        <h3 style={{ marginBottom: '1rem' }}>Local DNS Resolution Policy</h3>
        <Form>
          {policyOptions.map((option) => (
            <div key={option.value} style={{ marginBottom: '0.5rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <Radio
                id={`policy-${option.value}`}
                name="policy"
                label={option.label}
                isChecked={policy === option.value}
                onChange={() => setPolicy(option.value)}
              />
              {option.stigRecommended && (
                <Tooltip content="STIG Recommended: Use explicitly approved DNS servers for maximum security">
                  <CheckCircleIcon color="green" />
                </Tooltip>
              )}
            </div>
          ))}
          <div style={{ display: 'flex' }}>
            <Button 
              variant="primary" 
              onClick={handleSavePolicy} 
              style={{ marginTop: '1rem' }}
            >
              Save Policy
            </Button>
          </div>
        </Form>
      </div>

      {/* Local DNS Resolution Forwarder */}
      <div style={{ marginBottom: '2rem', padding: '1rem', border: '1px solid #ccc', borderRadius: '12px' }}>
        <h3 style={{ marginBottom: '0.5rem' }}>Local DNS Resolution Forwarder</h3>
        <p style={{ color: '#6a6e73', marginBottom: '0' }}>This name server (bind)</p>
      </div>

      {/* Add IP Address */}
      <div style={{ marginBottom: '2rem', padding: '1rem', border: '1px solid #ccc', borderRadius: '12px' }}>
        <h3 style={{ marginBottom: '1rem' }}>Add IP Address</h3>
        <Form>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr', gap: '1rem', maxWidth: '600px' }}>
            <FormGroup label="IPv4 or IPv6 Address" fieldId="forwarder-ip">
              <TextInput
                type="text"
                id="forwarder-ip"
                value={newForwarderIp}
                onChange={(event, value) => setNewForwarderIp(value)}
                placeholder="8.8.8.8 or 2001:4860:4860::8888"
                isDisabled={validating}
              />
              <p style={{ fontSize: '0.875rem', color: '#6a6e73', marginTop: '0.25rem' }}>
                Will validate DNS response and DNSSEC support
              </p>
            </FormGroup>

            <div style={{ display: 'flex' }}>
              <Button 
                variant="primary" 
                onClick={handleAddForwarder}
                isDisabled={validating}
              >
                {validating ? 'Validating...' : 'Add'}
              </Button>
            </div>
          </div>
        </Form>
      </div>

      {/* Forwarder List */}
      <div style={{ marginBottom: '2rem', padding: '1rem', border: '1px solid #ccc', borderRadius: '12px' }}>
        <h3 style={{ marginBottom: '1rem' }}>Forwarder List</h3>
        
        {forwarders.length > 0 ? (
          <table className="pf-v6-c-table pf-m-compact" role="grid">
            <thead>
              <tr role="row">
                <th role="columnheader" scope="col">IP Address</th>
                <th role="columnheader" scope="col">DNSSEC Support</th>
                <th role="columnheader" scope="col"></th>
              </tr>
            </thead>
            <tbody role="rowgroup">
              {forwarders.map((forwarder, idx) => (
                <tr key={idx} role="row">
                  <td role="cell" style={{ fontFamily: 'monospace' }}>{forwarder.ip}</td>
                  <td role="cell">
                    {forwarder.supportsDnssec ? (
                      <span style={{ color: 'green' }}>✓ Yes</span>
                    ) : (
                      <span style={{ color: 'orange' }}>⚠ No</span>
                    )}
                  </td>
                  <td role="cell" className="pf-v6-c-table__action">
                    <Button variant="danger" onClick={() => handleDeleteForwarder(forwarder.ip)}>
                      Delete
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p style={{ textAlign: 'center', fontStyle: 'italic', color: '#6a6e73' }}>
            No forwarders configured
          </p>
        )}
      </div>
    </PageSection>
  );
};
