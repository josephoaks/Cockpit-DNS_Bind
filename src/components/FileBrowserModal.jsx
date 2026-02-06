import React, { useState, useEffect } from 'react';
import {
  Modal,
  ModalVariant,
  ModalBody,
  ModalFooter,
  Button,
  Spinner,
  Alert,
  Breadcrumb,
  BreadcrumbItem,
} from '@patternfly/react-core';
import { FolderIcon, FileIcon } from '@patternfly/react-icons';
import cockpit from 'cockpit';

export const FileBrowserModal = ({ isOpen, onClose, onSelect, fileFilter = '.key' }) => {
  // Allowed root directories - user cannot navigate outside these
  const ALLOWED_ROOTS = [
    '/etc/named.d',
    '/tmp',
    '/home', // Will show user's home dir via cockpit.user
  ];

  const [currentPath, setCurrentPath] = useState('/etc/named.d');
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [userHome, setUserHome] = useState(null);

  useEffect(() => {
    // Get current cockpit user's home directory
    cockpit.user().then(user => {
      setUserHome(user.home || '/home');
    });
  }, []);

  useEffect(() => {
    if (isOpen) {
      loadItems(currentPath);
    }
  }, [isOpen, currentPath]);

  const isPathAllowed = (path) => {
    // Check if path starts with any allowed root
    return ALLOWED_ROOTS.some(root => path.startsWith(root)) || 
           (userHome && path.startsWith(userHome));
  };

  const loadItems = async (path) => {
    // Security check
    if (!isPathAllowed(path)) {
      setError('Access denied: path outside allowed directories');
      return;
    }

    setLoading(true);
    setError(null);

    try {
      // List directories and files separately
      const lsOutput = await cockpit.spawn(
        ['ls', '-1Ap', path],
        { superuser: 'try', err: 'out' }
      );

      const entries = lsOutput.trim().split('\n').filter(e => e && e !== '../');
      
      const itemList = [];

      // Add parent directory link if not at root
      const parentPath = path.split('/').slice(0, -1).join('/') || '/';
      if (path !== '/' && isPathAllowed(parentPath)) {
        itemList.push({
          name: '..',
          path: parentPath,
          type: 'directory',
          isParent: true
        });
      }

      // Process entries
      for (const entry of entries) {
        const fullPath = `${path}/${entry}`.replace(/\/+/g, '/');
        const isDir = entry.endsWith('/');
        const cleanName = entry.replace(/\/$/, '');

        if (isDir) {
          // Only show directories if they're within allowed paths
          if (isPathAllowed(fullPath)) {
            itemList.push({
              name: cleanName,
              path: fullPath,
              type: 'directory'
            });
          }
        } else {
          // Show files that match filter
          if (!fileFilter || cleanName.endsWith(fileFilter)) {
            itemList.push({
              name: cleanName,
              path: fullPath,
              type: 'file'
            });
          }
        }
      }

      setItems(itemList);
      setLoading(false);
    } catch (err) {
      setError('Failed to list directory: ' + err.message);
      setItems([]);
      setLoading(false);
    }
  };

  const handleItemClick = (item) => {
    if (item.type === 'directory') {
      setCurrentPath(item.path);
    } else {
      onSelect(item.path);
      onClose();
    }
  };

  const handleRootSelect = (root) => {
    if (root === '/home' && userHome) {
      setCurrentPath(userHome);
    } else {
      setCurrentPath(root);
    }
  };

  const getBreadcrumbs = () => {
    const parts = currentPath.split('/').filter(p => p);
    const crumbs = [{ name: 'root', path: '/' }];
    
    let accumulated = '';
    for (const part of parts) {
      accumulated += '/' + part;
      if (isPathAllowed(accumulated)) {
        crumbs.push({ name: part, path: accumulated });
      }
    }
    
    return crumbs;
  };

  return (
    <Modal
      variant={ModalVariant.large}
      title="Select TSIG Key File"
      isOpen={isOpen}
      onClose={onClose}
    >
      <ModalBody>
        {/* Root directory selector */}
        <div style={{ marginBottom: '1rem', display: 'flex', gap: '0.5rem' }}>
          <strong>Quick access:</strong>
          <Button 
            variant="link" 
            isInline 
            onClick={() => handleRootSelect('/etc/named.d')}
          >
            /etc/named.d
          </Button>
          <Button 
            variant="link" 
            isInline 
            onClick={() => handleRootSelect('/tmp')}
          >
            /tmp
          </Button>
          <Button 
            variant="link" 
            isInline 
            onClick={() => handleRootSelect('/home')}
          >
            Home
          </Button>
        </div>

        {/* Breadcrumb navigation */}
        <Breadcrumb style={{ marginBottom: '1rem' }}>
          {getBreadcrumbs().map((crumb, idx, arr) => (
            <BreadcrumbItem
              key={crumb.path}
              isActive={idx === arr.length - 1}
              onClick={() => idx !== arr.length - 1 && setCurrentPath(crumb.path)}
              style={{ cursor: idx !== arr.length - 1 ? 'pointer' : 'default' }}
            >
              {crumb.name}
            </BreadcrumbItem>
          ))}
        </Breadcrumb>

        {error && (
          <Alert variant="danger" title={error} isInline style={{ marginBottom: '1rem' }} />
        )}

        {loading ? (
          <div style={{ textAlign: 'center', padding: '2rem' }}>
            <Spinner size="lg" />
          </div>
        ) : (
          <div style={{ 
            maxHeight: '400px', 
            overflowY: 'auto', 
            border: '1px solid #ccc', 
            borderRadius: '4px' 
          }}>
            {items.length > 0 ? (
              <table className="pf-v6-c-table pf-m-compact pf-m-hoverable" role="grid">
                <tbody role="rowgroup">
                  {items.map((item, idx) => (
                    <tr 
                      key={idx} 
                      role="row" 
                      style={{ cursor: 'pointer' }}
                      onClick={() => handleItemClick(item)}
                    >
                      <td role="cell" style={{ padding: '0.5rem', width: '32px' }}>
                        {item.type === 'directory' ? (
                          <FolderIcon color="#0066cc" />
                        ) : (
                          <FileIcon color="#6a6e73" />
                        )}
                      </td>
                      <td role="cell" style={{ padding: '0.5rem' }}>
                        {item.isParent ? (
                          <strong>{item.name}</strong>
                        ) : (
                          item.name
                        )}
                      </td>
                      <td role="cell" style={{ 
                        padding: '0.5rem', 
                        fontSize: '0.875rem', 
                        color: '#6a6e73' 
                      }}>
                        {item.type === 'directory' ? 'Folder' : 'File'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <div style={{ 
                textAlign: 'center', 
                padding: '2rem', 
                fontStyle: 'italic', 
                color: '#6a6e73' 
              }}>
                No items found
              </div>
            )}
          </div>
        )}

        <div style={{ 
          marginTop: '1rem', 
          padding: '0.5rem', 
          backgroundColor: '#f5f5f5', 
          borderRadius: '4px',
          fontSize: '0.875rem',
          color: '#6a6e73'
        }}>
          <strong>Current path:</strong> {currentPath}
        </div>
      </ModalBody>
      <ModalFooter>
        <Button variant="link" onClick={onClose}>
          Cancel
        </Button>
      </ModalFooter>
    </Modal>
  );
};
