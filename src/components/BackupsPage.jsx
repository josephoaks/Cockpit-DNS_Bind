// =============================================================================
// src/components/BackupsPage.jsx
//
// Browse the snapshots taken before every write and put one back.
//
// This is a top-level tab rather than something under DNS Zones, because
// backups cover named.conf as well as zone files and are not specific to any
// one zone.
//
// A backup is not automatically good -- it may predate a fix, or have been
// taken from a file that was already broken -- so nothing is restored without
// being previewed and validated first, and the file being replaced is itself
// snapshotted on the way past.
// =============================================================================

import React, { useEffect, useState } from 'react';
import {
  Alert,
  Button,
  PageSection,
  Spinner,
  Title,
} from '@patternfly/react-core';
import { spawnBindctl } from '../utils/backend';

const shortName = (path) => path.split('/').pop();

// Backups are stamped YYYYMMDD-HHMMSS.
const prettyStamp = (stamp) => {
  const m = /^(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})(\d{2})$/.exec(stamp || '');
  if (!m) return stamp;
  return `${m[1]}-${m[2]}-${m[3]} ${m[4]}:${m[5]}:${m[6]}`;
};

const prettySize = (bytes) =>
  (bytes < 1024 ? `${bytes} B` : `${(bytes / 1024).toFixed(1)} KB`);

export const BackupsPage = () => {
  const [groups, setGroups] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [preview, setPreview] = useState(null);
  const [result, setResult] = useState(null);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      setGroups(JSON.parse(await spawnBindctl(['list-backups'])));
    } catch (err) {
      setError('Could not read the backup directory: ' + err.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const openPreview = async (group, version) => {
    setBusy(true);
    setError(null);
    try {
      const data = JSON.parse(await spawnBindctl(['read-backup', version.backup]));
      if (data.error) {
        setError(data.error);
        return;
      }
      setPreview({ ...data, group, version });
    } catch (err) {
      setError('Could not read that backup: ' + err.message);
    } finally {
      setBusy(false);
    }
  };

  const doRestore = async () => {
    if (!preview) return;
    const isZone = !preview.path.endsWith('named.conf');
    // The zone name is needed so the restored file can be checked against its
    // own origin before it goes live.
    const zoneName = isZone ? shortName(preview.path) : null;
    if (!confirm(`Replace ${preview.path} with the copy taken at `
      + `${prettyStamp(preview.version.taken)}?\n\n`
      + 'The current file is backed up first, so this can be undone.')) return;

    setBusy(true);
    setError(null);
    try {
      const args = ['restore-backup', preview.version.backup];
      if (zoneName) args.push(zoneName);
      const res = JSON.parse(await spawnBindctl(args));
      if (res.error) {
        setError(res.detail ? `${res.error}\n\n${res.detail}` : res.error);
        return;
      }
      setResult(res);
      setPreview(null);
      await load();
    } catch (err) {
      setError('Restore failed: ' + err.message);
    } finally {
      setBusy(false);
    }
  };

  if (loading) {
    return (
      <PageSection padding={{ default: 'padding' }}>
        <Spinner size="lg" />
      </PageSection>
    );
  }

  return (
    <PageSection padding={{ default: 'padding' }}>
      <Title headingLevel="h2" size="lg" style={{ marginBottom: '0.5rem' }}>
        Backups
      </Title>
      <p style={{ fontSize: '0.875rem', color: '#6a6e73', marginBottom: '1rem' }}>
        A copy of named.conf or a zone file is taken automatically before every
        change. The ten most recent versions of each file are kept, for up to
        ninety days.
      </p>

      {error && (
        <Alert variant="danger" isInline title="Nothing was changed"
          style={{ marginBottom: '1rem' }}
          actionClose={<Button variant="plain" onClick={() => setError(null)}>&times;</Button>}>
          <pre style={{ whiteSpace: 'pre-wrap', margin: 0, fontSize: '0.8rem' }}>{error}</pre>
        </Alert>
      )}

      {result && (
        <Alert variant="success" isInline title="Restored"
          style={{ marginBottom: '1rem' }}
          actionClose={<Button variant="plain" onClick={() => setResult(null)}>&times;</Button>}>
          <p><code>{result.path}</code> was replaced.</p>
          {result.undo && (
            <p>The version it replaced was saved as a new backup, so this can be undone.</p>
          )}
          {result.reload && result.reload.status !== 'reloaded' && (
            <p>{result.reload.message}</p>
          )}
        </Alert>
      )}

      {preview ? (
        <>
          <div style={{ display: 'flex', alignItems: 'center', gap: '1rem',
            marginBottom: '0.75rem' }}>
            <span>
              <strong>{preview.path}</strong> as it was at{' '}
              {prettyStamp(preview.version.taken)}
            </span>
            <span style={{ marginLeft: 'auto', display: 'flex', gap: '0.5rem' }}>
              <Button variant="danger" onClick={doRestore} isDisabled={busy}>
                {busy ? 'Restoring...' : 'Restore this version'}
              </Button>
              <Button variant="secondary" onClick={() => setPreview(null)} isDisabled={busy}>
                Back to list
              </Button>
            </span>
          </div>
          <div style={{ display: 'flex', gap: '1rem' }}>
            <div style={{ flex: 1, minWidth: 0 }}>
              <p style={{ fontSize: '0.8rem', color: '#6a6e73' }}>Backup</p>
              <pre style={{ maxHeight: '55vh', overflow: 'auto', fontSize: '0.75rem',
                whiteSpace: 'pre' }}>{preview.content}</pre>
            </div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <p style={{ fontSize: '0.8rem', color: '#6a6e73' }}>Current file</p>
              <pre style={{ maxHeight: '55vh', overflow: 'auto', fontSize: '0.75rem',
                whiteSpace: 'pre' }}>
                {preview.current || '(the file is not there at the moment)'}
              </pre>
            </div>
          </div>
        </>
      ) : groups.length === 0 ? (
        <p>No backups have been taken yet.</p>
      ) : (
        <table className="pf-v6-c-table pf-m-compact" role="grid"
          aria-label="Backups" style={{ width: '100%', tableLayout: 'fixed' }}>
          <colgroup>
            <col style={{ width: '40%' }} />
            <col style={{ width: '13rem' }} />
            <col style={{ width: '7rem' }} />
            <col />
          </colgroup>
          <thead>
            <tr role="row">
              <th role="columnheader" scope="col">File</th>
              <th role="columnheader" scope="col">Taken</th>
              <th role="columnheader" scope="col">Size</th>
              <th role="columnheader" scope="col"> </th>
            </tr>
          </thead>
          <tbody>
            {groups.flatMap((group) => group.versions.map((version, i) => (
              <tr role="row" key={version.backup}>
                <td role="cell" style={{ wordBreak: 'break-all' }}>
                  {i === 0 && (
                    <>
                      <span title={group.path}>{shortName(group.path)}</span>
                      {!group.exists && (
                        <span style={{ color: '#c9190b', fontSize: '0.8rem',
                          marginLeft: '0.5rem' }}>
                          no longer present
                        </span>
                      )}
                      <div style={{ fontSize: '0.75rem', color: '#6a6e73' }}>
                        {group.path}
                      </div>
                    </>
                  )}
                </td>
                <td role="cell" style={{ fontSize: '0.875rem' }}>
                  {prettyStamp(version.taken)}
                  {i === 0 && <span style={{ color: '#6a6e73' }}> — most recent</span>}
                </td>
                <td role="cell" style={{ fontSize: '0.875rem' }}>
                  {prettySize(version.size)}
                </td>
                <td role="cell">
                  <Button variant="secondary" size="sm" isDisabled={busy}
                    onClick={() => openPreview(group, version)}>
                    View
                  </Button>
                </td>
              </tr>
            )))}
          </tbody>
        </table>
      )}
    </PageSection>
  );
};
