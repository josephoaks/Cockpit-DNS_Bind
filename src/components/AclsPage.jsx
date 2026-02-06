import React, { useEffect, useState } from 'react';
import {
  Button,
  PageSection,
  Spinner,
  Alert,
  Form,
  FormGroup,
  TextInput,
  TextArea,
  Modal,
  ModalBody,
  ModalFooter,
  ModalVariant,
} from '@patternfly/react-core';
import { spawnAclBackend } from '../utils/backend';

export const AclsPage = () => {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [acls, setAcls] = useState([]);

  // Add ACL state
  const [aclName, setAclName] = useState('');
  const [aclValue, setAclValue] = useState('');

  // Edit ACL state
  const [showEditModal, setShowEditModal] = useState(false);
  const [editingAcl, setEditingAcl] = useState(null);
  const [editAclName, setEditAclName] = useState('');
  const [editAclValue, setEditAclValue] = useState('');

  useEffect(() => {
    loadAcls();
  }, []);

  const loadAcls = async () => {
    try {
      setLoading(true);
      setError(null);
      const output = await spawnAclBackend(['list']);
      const result = JSON.parse(output);

      if (result.error) {
        setError(result.error);
        setAcls([]);
      } else {
        setAcls(result.acls || []);
      }
      setLoading(false);
    } catch (err) {
      console.error('Failed to load ACLs:', err);
      setError('Failed to load ACLs: ' + err.message);
      setAcls([]);
      setLoading(false);
    }
  };

  const handleAddAcl = async () => {
    if (!aclName.trim()) {
      alert('Please enter an ACL name');
      return;
    }

    if (!aclValue.trim()) {
      alert('Please enter ACL values (IP addresses, networks, or keywords)');
      return;
    }

    try {
      // Split by newlines or semicolons, trim whitespace
      const values = aclValue
        .split(/[\n;]+/)
        .map(v => v.trim())
        .filter(v => v);

      const data = {
        name: aclName.trim(),
        values: values
      };

      const output = await spawnAclBackend(['add', JSON.stringify(data)]);
      const result = JSON.parse(output);

      if (result.error) {
        setError('Failed to add ACL: ' + result.error);
        return;
      }

      alert(`ACL "${aclName}" added successfully`);
      setAclName('');
      setAclValue('');
      await loadAcls();
    } catch (err) {
      console.error('Failed to add ACL:', err);
      setError('Failed to add ACL: ' + err.message);
    }
  };

  const handleEditAcl = (acl) => {
    setEditingAcl(acl);
    setEditAclName(acl.name);
    setEditAclValue(acl.values.join('\n'));
    setShowEditModal(true);
  };

  const handleSaveEdit = async () => {
    if (!editAclValue.trim()) {
      alert('Please enter ACL values');
      return;
    }

    try {
      const values = editAclValue
        .split(/[\n;]+/)
        .map(v => v.trim())
        .filter(v => v);

      const data = {
        name: editAclName,
        values: values
      };

      const output = await spawnAclBackend(['update', JSON.stringify(data)]);
      const result = JSON.parse(output);

      if (result.error) {
        setError('Failed to update ACL: ' + result.error);
        return;
      }

      alert(`ACL "${editAclName}" updated successfully`);
      setShowEditModal(false);
      setEditingAcl(null);
      await loadAcls();
    } catch (err) {
      console.error('Failed to update ACL:', err);
      setError('Failed to update ACL: ' + err.message);
    }
  };

  const handleDeleteAcl = async (aclName) => {
    if (!confirm(`Delete ACL "${aclName}"?`)) return;

    try {
      const data = { name: aclName };
      const output = await spawnAclBackend(['delete', JSON.stringify(data)]);
      const result = JSON.parse(output);

      if (result.error) {
        setError('Failed to delete ACL: ' + result.error);
        return;
      }

      await loadAcls();
    } catch (err) {
      console.error('Failed to delete ACL:', err);
      setError('Failed to delete ACL: ' + err.message);
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
      <h1 style={{ marginBottom: '1.5rem' }}>DNS Server: ACLs</h1>

      {error && (
        <Alert
          variant="danger"
          title={error}
          isInline
          actionClose={<Button variant="plain" onClick={() => setError(null)}>×</Button>}
          style={{ marginBottom: '1rem' }}
        />
      )}

      {/* Option Setup */}
      <div style={{ marginBottom: '2rem', padding: '1rem', border: '1px solid #ccc', borderRadius: '12px' }}>
        <h3 style={{ marginBottom: '1rem' }}>Option Setup</h3>
        <Form>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr', gap: '1rem', alignItems: 'end', maxWidth: '1000px' }}>
            <FormGroup label="Name" fieldId="acl-name">
              <TextInput
                type="text"
                id="acl-name"
                value={aclName}
                onChange={(event, value) => setAclName(value)}
                placeholder="trusted"
              />
            </FormGroup>

            <FormGroup label="Value" fieldId="acl-value">
              <TextArea
                id="acl-value"
                value={aclValue}
                onChange={(event, value) => setAclValue(value)}
                placeholder="192.168.1.0/24&#10;10.0.0.5&#10;localhost"
                rows={3}
                style={{ fontFamily: 'monospace' }}
              />
              <p style={{ fontSize: '0.875rem', color: '#6a6e73', marginTop: '0.25rem' }}>
                One IP/network/keyword per line. Examples: 192.168.1.0/24, localhost, localnets
              </p>
            </FormGroup>

            <div style={{ display: 'flex' }}>
              <Button variant="primary" onClick={handleAddAcl}>
                Add
              </Button>
            </div>
          </div>
        </Form>
      </div>

      {/* Current ACL List */}
      <div style={{ marginBottom: '2rem', padding: '1rem', border: '1px solid #ccc', borderRadius: '12px' }}>
        <h3 style={{ marginBottom: '1rem' }}>Current ACL List</h3>
        <table className="pf-v6-c-table pf-m-compact" role="grid">
          <thead>
            <tr role="row">
              <th role="columnheader" scope="col" style={{ width: '20%' }}>ACL</th>
              <th role="columnheader" scope="col" style={{ width: '60%' }}>Value</th>
              <th role="columnheader" scope="col" style={{ width: '20%' }}></th>
            </tr>
          </thead>
          <tbody role="rowgroup">
            {acls.length > 0 ? (
              acls.map((acl, idx) => (
                <tr key={idx} role="row">
                  <td role="cell" style={{ verticalAlign: 'top', paddingTop: '1rem' }}>
                    <strong>{acl.name}</strong>
                  </td>
                  <td role="cell" style={{ fontFamily: 'monospace', fontSize: '0.875rem', verticalAlign: 'top', paddingTop: '1rem' }}>
                    {acl.values.map((value, vidx) => (
                      <div key={vidx}>{value};</div>
                    ))}
                  </td>
                  <td role="cell" className="pf-v6-c-table__action" style={{ verticalAlign: 'top', paddingTop: '0.75rem' }}>
                    <Button 
                      variant="secondary" 
                      onClick={() => handleEditAcl(acl)}
                      style={{ marginRight: '0.5rem' }}
                    >
                      Edit
                    </Button>
                    <Button variant="danger" onClick={() => handleDeleteAcl(acl.name)}>
                      Delete
                    </Button>
                  </td>
                </tr>
              ))
            ) : (
              <tr role="row">
                <td role="cell" colSpan="3" style={{ textAlign: 'center', fontStyle: 'italic' }}>
                  No ACLs configured
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {/* Edit ACL Modal */}
      <Modal
        variant={ModalVariant.medium}
        title={`Edit ACL: ${editAclName}`}
        isOpen={showEditModal}
        onClose={() => setShowEditModal(false)}
      >
        <ModalBody>
          <Form>
            <FormGroup label="Name" fieldId="edit-acl-name">
              <TextInput
                type="text"
                id="edit-acl-name"
                value={editAclName}
                isReadOnly
              />
            </FormGroup>

            <FormGroup label="Value" fieldId="edit-acl-value">
              <TextArea
                id="edit-acl-value"
                value={editAclValue}
                onChange={(event, value) => setEditAclValue(value)}
                rows={8}
                style={{ fontFamily: 'monospace' }}
              />
              <p style={{ fontSize: '0.875rem', color: '#6a6e73', marginTop: '0.25rem' }}>
                One IP/network/keyword per line
              </p>
            </FormGroup>
          </Form>
        </ModalBody>
        <ModalFooter>
          <Button variant="primary" onClick={handleSaveEdit}>
            Save
          </Button>
          <Button variant="link" onClick={() => setShowEditModal(false)}>
            Cancel
          </Button>
        </ModalFooter>
      </Modal>
    </PageSection>
  );
};
