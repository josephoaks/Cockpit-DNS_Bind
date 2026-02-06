import React, { useEffect, useState } from 'react';
import {
  Button,
  PageSection,
  Spinner,
  Alert,
  Form,
  FormGroup,
  TextInput,
  Modal,
  ModalBody,
  ModalFooter,
  ModalVariant,
} from '@patternfly/react-core';
import { spawnTsigBackend } from '../utils/backend';
import { FileBrowserModal } from './FileBrowserModal';

export const TsigKeysPage = () => {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [tsigKeys, setTsigKeys] = useState([]);

  // Add Existing Key state
  const [existingKeyPath, setExistingKeyPath] = useState('');

  // Create New Key state
  const [newKeyId, setNewKeyId] = useState('');
  const [newKeyFilename, setNewKeyFilename] = useState('');
  const [newKeyAlgorithm, setNewKeyAlgorithm] = useState('hmac-sha256');

  // Upload state
  const [uploadFile, setUploadFile] = useState(null);

  // Overwrite confirmation modal
  const [showOverwriteModal, setShowOverwriteModal] = useState(false);
  const [conflictKeyName, setConflictKeyName] = useState('');
  const [tempUploadPath, setTempUploadPath] = useState('');

  // File browser modal
  const [showFileBrowser, setShowFileBrowser] = useState(false);

  useEffect(() => {
    loadTsigKeys();
  }, []);

  const loadTsigKeys = async () => {
    try {
      setLoading(true);
      setError(null);
      const output = await spawnTsigBackend(['list']);
      const result = JSON.parse(output);
      
      if (result.error) {
        setError(result.error);
        setTsigKeys([]);
      } else {
        setTsigKeys(result.keys || []);
      }
      setLoading(false);
    } catch (err) {
      console.error('Failed to load TSIG keys:', err);
      setError('Failed to load TSIG keys: ' + err.message);
      setTsigKeys([]);
      setLoading(false);
    }
  };

  const handleBrowseServer = () => {
    setShowFileBrowser(true);
  };

  const handleFileSelect = (filepath) => {
    setExistingKeyPath(filepath);
    setShowFileBrowser(false);
  };

  const handleFileUpload = (event) => {
    const file = event.target.files[0];
    if (file) {
      setUploadFile(file);
    }
  };

  const handleUploadKey = async () => {
    if (!uploadFile) {
      alert('Please select a file to upload');
      return;
    }

    try {
      // Read file contents
      const reader = new FileReader();
      reader.onload = async (e) => {
        const fileContents = e.target.result;

        // Upload to backend for validation
        const data = {
          filename: uploadFile.name,
          content: fileContents
        };

        const output = await spawnTsigBackend(['upload', JSON.stringify(data)]);
        const result = JSON.parse(output);

        if (result.error) {
          // Check if it's a conflict
          if (result.conflict) {
            setConflictKeyName(result.key_name);
            setTempUploadPath(result.temp_path || '');
            setShowOverwriteModal(true);
            return;
          }
          setError('Failed to upload key: ' + result.error);
          return;
        }

        // Success - now import it
        if (result.status === 'ok') {
          const importData = {
            temp_path: result.temp_path,
            final_filename: uploadFile.name,
            overwrite: false
          };

          const importOutput = await spawnTsigBackend(['import', JSON.stringify(importData)]);
          const importResult = JSON.parse(importOutput);

          if (importResult.error) {
            setError('Failed to import key: ' + importResult.error);
            return;
          }

          alert(`TSIG key "${importResult.key_name}" imported successfully`);
          setUploadFile(null);
          document.getElementById('file-upload-input').value = '';
          await loadTsigKeys();
        }
      };

      reader.readAsText(uploadFile);
    } catch (err) {
      console.error('Failed to upload key:', err);
      setError('Failed to upload key: ' + err.message);
    }
  };

  const handleConfirmOverwrite = async () => {
    try {
      const data = {
        temp_path: tempUploadPath,
        final_filename: uploadFile.name,
        overwrite: true
      };

      const output = await spawnTsigBackend(['import', JSON.stringify(data)]);
      const result = JSON.parse(output);

      if (result.error) {
        setError('Failed to import key: ' + result.error);
        return;
      }

      alert(`TSIG key "${conflictKeyName}" overwritten successfully`);
      setShowOverwriteModal(false);
      setUploadFile(null);
      document.getElementById('file-upload-input').value = '';
      await loadTsigKeys();
    } catch (err) {
      console.error('Failed to import key:', err);
      setError('Failed to import key: ' + err.message);
    }
  };

  const handleCancelOverwrite = async () => {
    // Cleanup temp file
    try {
      if (tempUploadPath) {
        await spawnTsigBackend(['cleanup', JSON.stringify({ temp_path: tempUploadPath })]);
      }
    } catch (err) {
      console.error('Failed to cleanup temp file:', err);
    }
    setShowOverwriteModal(false);
    setUploadFile(null);
    document.getElementById('file-upload-input').value = '';
  };

  const handleAddExistingKey = async () => {
    if (!existingKeyPath.trim()) {
      alert('Please enter a file path');
      return;
    }

    try {
      const data = { path: existingKeyPath.trim() };
      const output = await spawnTsigBackend(['add-existing', JSON.stringify(data)]);
      const result = JSON.parse(output);

      if (result.error) {
        setError('Failed to add key: ' + result.error);
        return;
      }

      alert(`TSIG key "${result.key_name}" added successfully`);
      setExistingKeyPath('');
      await loadTsigKeys();
    } catch (err) {
      console.error('Failed to add key:', err);
      setError('Failed to add key: ' + err.message);
    }
  };

  const handleGenerateKey = async () => {
    if (!newKeyId.trim()) {
      alert('Please enter a Key ID');
      return;
    }

    const filename = newKeyFilename.trim() || `/etc/named.d/${newKeyId.trim()}.key`;

    try {
      const data = {
        name: newKeyId.trim(),
        algorithm: newKeyAlgorithm
      };

      const output = await spawnTsigBackend(['generate', JSON.stringify(data)]);
      const result = JSON.parse(output);

      if (result.error) {
        setError('Failed to generate key: ' + result.error);
        return;
      }

      alert(`TSIG key "${newKeyId}" generated successfully`);
      setNewKeyId('');
      setNewKeyFilename('');
      setNewKeyAlgorithm('hmac-sha256');
      await loadTsigKeys();
    } catch (err) {
      console.error('Failed to generate key:', err);
      setError('Failed to generate key: ' + err.message);
    }
  };

  const handleDeleteKey = async (keyName, keyFile) => {
    if (!confirm(`Delete TSIG key "${keyName}"?`)) return;

    try {
      const data = { name: keyName };
      const output = await spawnTsigBackend(['delete', JSON.stringify(data)]);
      const result = JSON.parse(output);

      if (result.error) {
        setError('Failed to delete key: ' + result.error);
        return;
      }

      await loadTsigKeys();
    } catch (err) {
      console.error('Failed to delete key:', err);
      setError('Failed to delete key: ' + err.message);
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
      <h1 style={{ marginBottom: '1.5rem' }}>DNS Server: TSIG Keys</h1>

      {error && (
        <Alert
          variant="danger"
          title={error}
          isInline
          actionClose={<Button variant="plain" onClick={() => setError(null)}>×</Button>}
          style={{ marginBottom: '1rem' }}
        />
      )}

      {/* Add an Existing TSIG Key */}
      <div style={{ marginBottom: '2rem', padding: '1rem', border: '1px solid #ccc', borderRadius: '12px' }}>
        <h3 style={{ marginBottom: '1rem' }}>Add an Existing TSIG Key</h3>
        <Form>
          <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center', maxWidth: '800px' }}>
            <FormGroup label="Filename" fieldId="existing-key-path" style={{ flex: 1 }}>
              <TextInput
                type="text"
                id="existing-key-path"
                value={existingKeyPath}
                onChange={(event, value) => setExistingKeyPath(value)}
                placeholder="/etc/named.d/mykey.key"
              />
            </FormGroup>
            <div style={{ display: 'flex', gap: '0.5rem' }}>
              <Button variant="secondary" onClick={handleBrowseServer}>
                Browse (Server)
              </Button>
              <Button variant="secondary" onClick={() => document.getElementById('file-upload-input').click()}>
                Upload (Desktop)
              </Button>
              <input
                type="file"
                id="file-upload-input"
                accept=".key,.conf"
                style={{ display: 'none' }}
                onChange={handleFileUpload}
              />
              <Button variant="primary" onClick={uploadFile ? handleUploadKey : handleAddExistingKey}>
                {uploadFile ? 'Import' : 'Add'}
              </Button>
            </div>
          </div>
          {uploadFile && (
            <p style={{ marginTop: '0.5rem', fontSize: '0.875rem', color: '#6a6e73' }}>
              Selected file: {uploadFile.name}
            </p>
          )}
        </Form>
      </div>

      {/* Create a New TSIG Key */}
      <div style={{ marginBottom: '2rem', padding: '1rem', border: '1px solid #ccc', borderRadius: '12px' }}>
        <h3 style={{ marginBottom: '1rem' }}>Create a New TSIG Key</h3>
        <Form>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '1rem', maxWidth: '800px' }}>
            <FormGroup label="Key ID" fieldId="new-key-id">
              <TextInput
                type="text"
                id="new-key-id"
                value={newKeyId}
                onChange={(event, value) => {
                  setNewKeyId(value);
                  if (!newKeyFilename) {
                    setNewKeyFilename(`/etc/named.d/${value}.key`);
                  }
                }}
                placeholder="mykey"
              />
            </FormGroup>

            <FormGroup label="Filename" fieldId="new-key-filename">
              <TextInput
                type="text"
                id="new-key-filename"
                value={newKeyFilename}
                onChange={(event, value) => setNewKeyFilename(value)}
                placeholder="/etc/named.d/mykey.key"
              />
            </FormGroup>

            <FormGroup label="Algorithm" fieldId="new-key-algorithm">
              <select
                id="new-key-algorithm"
                value={newKeyAlgorithm}
                onChange={(e) => setNewKeyAlgorithm(e.target.value)}
                className="pf-v6-c-form-control"
                style={{
                  width: '100%',
                  height: '38px',
                  padding: '8px 10px',
                }}
              >
                <option value="hmac-sha256">HMAC-SHA256</option>
                <option value="hmac-sha512">HMAC-SHA512</option>
                <option value="hmac-sha1">HMAC-SHA1 (Legacy)</option>
                <option value="hmac-md5">HMAC-MD5 (Deprecated)</option>
              </select>
            </FormGroup>
          </div>

          <div style={{ display: 'flex' }}>
            <Button variant="primary" onClick={handleGenerateKey} style={{ marginTop: '-2rem' }}>Generate</Button>
          </div>
        </Form>
      </div>

      {/* Current TSIG Keys */}
      <div style={{ marginBottom: '2rem', padding: '1rem', border: '1px solid #ccc', borderRadius: '12px' }}>
        <h3 style={{ marginBottom: '1rem' }}>Current TSIG Keys</h3>
        <table className="pf-v6-c-table pf-m-compact" role="grid">
          <thead>
            <tr role="row">
              <th role="columnheader" scope="col">Key ID</th>
              <th role="columnheader" scope="col">Filename</th>
              <th role="columnheader" scope="col"></th>
            </tr>
          </thead>
          <tbody role="rowgroup">
            {tsigKeys.length > 0 ? (
              tsigKeys.map((key, idx) => (
                <tr key={idx} role="row">
                  <td role="cell">{key.name}</td>
                  <td role="cell">{key.filename || key.source || 'N/A'}</td>
                  <td role="cell" className="pf-v6-c-table__action">
                    <Button variant="danger" onClick={() => handleDeleteKey(key.name, key.file)}>
                      Delete
                    </Button>
                  </td>
                </tr>
              ))
            ) : (
              <tr role="row">
                <td role="cell" colSpan="3" style={{ textAlign: 'center', fontStyle: 'italic' }}>
                  No TSIG keys configured
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {/* Overwrite Confirmation Modal */}
      <Modal
        variant={ModalVariant.small}
        title="Key Already Exists"
        isOpen={showOverwriteModal}
        onClose={handleCancelOverwrite}
      >
        <ModalBody>
          <p>A TSIG key named "{conflictKeyName}" already exists but has different content.</p>
          <p style={{ marginTop: '1rem' }}>Do you want to overwrite it?</p>
        </ModalBody>
        <ModalFooter>
          <Button variant="danger" onClick={handleConfirmOverwrite}>
            Overwrite
          </Button>
          <Button variant="link" onClick={handleCancelOverwrite}>
            Cancel
          </Button>
        </ModalFooter>
      </Modal>

      {/* File Browser Modal */}
      <FileBrowserModal
        isOpen={showFileBrowser}
        onClose={() => setShowFileBrowser(false)}
        onSelect={handleFileSelect}
        fileFilter=".key"
      />
    </PageSection>
  );
};
