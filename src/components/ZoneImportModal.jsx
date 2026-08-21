import React, { useState } from 'react';
import {
  Alert,
  Button,
  Modal,
  ModalBody,
  ModalFooter,
  ModalVariant,
  Spinner,
} from '@patternfly/react-core';
import { spawnBackendInput } from '../utils/backend';

const readFile = (file) => new Promise((resolve, reject) => {
  const reader = new FileReader();
  reader.onload = () => resolve(reader.result);
  reader.onerror = () => reject(new Error(`Could not read ${file.name}`));
  reader.readAsText(file);
});

// Zone files are referenced in named.conf by a path relative to the server's
// directory ("master/pirate.com"), but uploads arrive as a flat set carrying
// only a basename. Matching on the basename is the only option available, so
// ambiguity is reported rather than guessed at.
const basename = (p) => (p || '').split('/').pop();

export const ZoneImportModal = ({ isOpen, onClose, onImported }) => {
  const [step, setStep] = useState('conf');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [rows, setRows] = useState([]);
  const [results, setResults] = useState(null);
  const [confNotes, setConfNotes] = useState(null);
  const [showDefaults, setShowDefaults] = useState(false);

  const reset = () => {
    setStep('conf');
    setBusy(false);
    setError(null);
    setRows([]);
    setResults(null);
    setConfNotes(null);
  };

  const close = () => {
    reset();
    onClose();
  };

  const handleConfUpload = async (event) => {
    const file = event.target.files && event.target.files[0];
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      const text = await readFile(file);
      const result = JSON.parse(await spawnBackendInput(['import-parse-conf'], text));
      if (result.error) {
        setError(result.detail ? `${result.error}\n\n${result.detail}` : result.error);
        setBusy(false);
        return;
      }
      setConfNotes({
        confValid: result.confValid,
        confMessage: result.confMessage,
        includes: result.includes || [],
      });
      setRows(result.zones.map((z) => ({
        ...z,
        // Default zones ship with every install and the local server already
        // has its own; importing them is never what someone wants.
        selected: !z.isDefault && !z.existsLocally && !z.invalid,
        replace: false,
        content: null,
        fileName: null,
        status: null,
      })));
      setStep('review');
    } catch (err) {
      setError('Failed to read named.conf: ' + err.message);
    } finally {
      setBusy(false);
    }
  };

  const setRow = (name, patch) => {
    setRows((prev) => prev.map((r) => (r.name === name ? { ...r, ...patch } : r)));
  };

  const attachZoneFile = async (row, file) => {
    if (!file) return;
    try {
      const text = await readFile(file);
      setRow(row.name, { content: text, fileName: file.name, status: { checking: true } });
      const res = JSON.parse(
        await spawnBackendInput(['import-validate-zone', row.name], text));
      // Only ever change `selected` here to switch it off: spreading an
      // undefined into the row would clear a selection the admin already made.
      const patch = {
        status: res.ok ? { ok: true } : { ok: false, message: res.message },
      };
      if (!res.ok) patch.selected = false;
      setRow(row.name, patch);
    } catch (err) {
      setRow(row.name, { status: { ok: false, message: err.message } });
    }
  };

  // A multi-file pick is matched to rows by basename, which is how an admin
  // who still has the old master/ directory will want to do this.
  const attachMany = async (files) => {
    const list = Array.from(files || []);
    const wanted = rows.filter((r) => r.needsFile && !r.isDefault);
    for (const file of list) {
      const matches = wanted.filter((r) => basename(r.sourceFile) === file.name);
      if (matches.length === 1) {
        // eslint-disable-next-line no-await-in-loop
        await attachZoneFile(matches[0], file);
      } else if (matches.length > 1) {
        setError(`${file.name} matches more than one zone `
          + `(${matches.map((m) => m.name).join(', ')}). Attach those individually.`);
      }
    }
  };

  const runImport = async () => {
    setBusy(true);
    setError(null);
    const out = [];
    for (const row of rows.filter((r) => r.selected)) {
      const meta = {
        name: row.name,
        type: row.type,
        replace: row.replace,
        primaries: row.primaries,
        forwarders: row.forwarders,
      };
      try {
        // eslint-disable-next-line no-await-in-loop
        const res = JSON.parse(await spawnBackendInput(
          ['import-zone', JSON.stringify(meta)], row.content || ''));
        out.push(res);
      } catch (err) {
        out.push({ zone: row.name, error: err.message });
      }
    }
    setResults(out);
    setStep('done');
    setBusy(false);
    onImported();
  };

  const importable = rows.filter((r) => r.selected);
  const blocked = importable.filter(
    (r) => r.needsFile && (!r.content || (r.status && r.status.ok === false)));

  const rowStatus = (row) => {
    // A default zone is never imported, so anything else about it is noise --
    // including the root hint zone, whose name is legitimately not importable.
    if (row.isDefault) return <span style={{ color: '#6a6e73' }}>Not imported</span>;
    if (row.invalid) {
      return (
        <span style={{ color: '#c9190b' }} title={row.invalid}>
          Invalid zone name
        </span>
      );
    }
    if (row.existsLocally && !row.replace) return 'Already exists here';
    if (!row.needsFile) return 'No zone file needed';
    if (!row.content) return <span style={{ color: '#6a6e73' }}>Needs zone file</span>;
    if (row.status && row.status.checking) return 'Checking...';
    if (row.status && row.status.ok) return <span style={{ color: '#3e8635' }}>Valid</span>;
    if (row.status && row.status.ok === false) {
      return (
        <span style={{ color: '#c9190b' }} title={row.status.message}>
          Failed named-checkzone
        </span>
      );
    }
    return '';
  };

  return (
    <Modal
      variant={ModalVariant.large}
      title="Import zones"
      isOpen={isOpen}
      onClose={close}
    >
      <ModalBody>
        {error && (
          <Alert variant="danger" isInline title="Import problem" style={{ marginBottom: '1rem' }}>
            <pre style={{ whiteSpace: 'pre-wrap', margin: 0 }}>{error}</pre>
          </Alert>
        )}

        {step === 'conf' && (
          <div>
            <p style={{ marginBottom: '1rem' }}>
              Upload the <code>named.conf</code> from the server you are migrating from.
              It is checked with <code>named-checkconf</code> and then read to find out
              which zones exist, what type each one is, and which zone file belongs to it.
            </p>
            <p style={{ marginBottom: '1rem', color: '#6a6e73', fontSize: '0.875rem' }}>
              Only zone declarations are imported. Options, forwarders, ACLs and logging
              settings belong to this server and are left alone.
            </p>
            <input type="file" accept=".conf,text/plain" onChange={handleConfUpload} />
            {busy && <Spinner size="md" style={{ marginLeft: '1rem' }} />}
          </div>
        )}

        {step === 'review' && (
          <div>
            {confNotes && confNotes.includes.length > 0 && (
              <Alert variant="warning" isInline style={{ marginBottom: '1rem' }}
                title="This configuration includes other files">
                <p>
                  Zones defined inside these includes are not listed below, because the
                  files live on the other server:
                </p>
                <ul>
                  {confNotes.includes.map((i) => <li key={i}><code>{i}</code></li>)}
                </ul>
                <p>
                  If any of them declare zones, import those separately.
                </p>
              </Alert>
            )}
            {confNotes && !confNotes.confValid && (
              <Alert variant="info" isInline style={{ marginBottom: '1rem' }}
                title="named-checkconf reported problems with this file">
                <p>
                  This is expected for a configuration from another server: includes and
                  option statements are checked against this machine, not the one it came
                  from. Only the zone declarations below are imported.
                </p>
                <pre style={{ whiteSpace: 'pre-wrap', margin: '0.5rem 0 0',
                  fontSize: '0.8rem' }}>{confNotes.confMessage}</pre>
              </Alert>
            )}
            <p style={{ marginBottom: '1rem' }}>
              Attach the zone file for each primary zone you want to import. You can select
              them all at once and they will be matched by filename.
            </p>
            <div style={{ marginBottom: '1rem' }}>
              <input type="file" multiple accept=".zone,text/plain"
                onChange={(e) => attachMany(e.target.files)} />
            </div>

            <table className="pf-v6-c-table pf-m-compact" role="grid"
              aria-label="Zones to import"
              style={{ width: '100%', tableLayout: 'fixed' }}>
              <colgroup>
                <col style={{ width: '4rem' }} />
                <col style={{ width: '34%' }} />
                <col style={{ width: '6rem' }} />
                <col style={{ width: '26%' }} />
                <col />
              </colgroup>
              <thead>
                <tr role="row">
                  <th role="columnheader" scope="col" style={{ whiteSpace: 'nowrap' }}>Import</th>
                  <th role="columnheader" scope="col" style={{ whiteSpace: 'nowrap' }}>Zone</th>
                  <th role="columnheader" scope="col" style={{ whiteSpace: 'nowrap' }}>Type</th>
                  <th role="columnheader" scope="col" style={{ whiteSpace: 'nowrap' }}>Zone file</th>
                  <th role="columnheader" scope="col" style={{ whiteSpace: 'nowrap' }}>Status</th>
                </tr>
              </thead>
              <tbody>
                {rows.filter((r) => showDefaults || !r.isDefault).map((row) => (
                  <tr role="row" key={row.name}>
                    <td role="cell">
                      <input
                        type="checkbox"
                        checked={!!row.selected}
                        disabled={!!row.invalid}
                        onChange={(e) => setRow(row.name, { selected: e.target.checked })}
                      />
                    </td>
                    <td role="cell" style={{ wordBreak: 'break-all' }}>
                      <span title={row.name}>
                        {row.name.length > 44 ? `${row.name.slice(0, 41)}...` : row.name}
                      </span>
                      {row.isDefault && (
                        <span style={{ color: '#6a6e73', fontSize: '0.8rem', marginLeft: '0.5rem' }}>
                          default zone
                        </span>
                      )}
                    </td>
                    <td role="cell">{row.type}</td>
                    <td role="cell">
                      {row.needsFile && !row.isDefault ? (
                        <>
                          {row.fileName
                            ? <span style={{ fontSize: '0.875rem' }}>{row.fileName}</span>
                            : <span style={{ color: '#6a6e73', fontSize: '0.875rem' }}>
                                {basename(row.sourceFile) || '—'}
                              </span>}
                          <input
                            type="file"
                            style={{ display: 'block', marginTop: '0.25rem',
                              fontSize: '0.7rem', maxWidth: '100%' }}
                            onChange={(e) => attachZoneFile(row, e.target.files && e.target.files[0])}
                          />
                        </>
                      ) : <span style={{ color: '#6a6e73' }}>—</span>}
                    </td>
                    <td role="cell" style={{ fontSize: '0.875rem' }}>
                      {rowStatus(row)}
                      {row.existsLocally && !row.invalid && !row.isDefault && (
                        <label style={{ display: 'block', fontSize: '0.8rem', marginTop: '0.25rem' }}>
                          <input
                            type="checkbox"
                            checked={!!row.replace}
                            onChange={(e) => setRow(row.name, { replace: e.target.checked })}
                          />
                          {' '}Replace the local copy
                        </label>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>

            {rows.some((r) => r.isDefault) && (
              <Button variant="link" isInline style={{ marginTop: '0.5rem' }}
                onClick={() => setShowDefaults(!showDefaults)}>
                {showDefaults
                  ? 'Hide default zones'
                  : `Show ${rows.filter((r) => r.isDefault).length} default zones`}
              </Button>
            )}

            {blocked.length > 0 && (
              <Alert variant="warning" isInline style={{ marginTop: '1rem' }}
                title={`${blocked.length} selected zone(s) still need a valid zone file`} />
            )}
          </div>
        )}

        {step === 'done' && results && (
          <div>
            <table className="pf-v6-c-table pf-m-compact" role="grid" aria-label="Import results">
              <thead>
                <tr role="row">
                  <th role="columnheader" scope="col">Zone</th>
                  <th role="columnheader" scope="col">Result</th>
                </tr>
              </thead>
              <tbody>
                {results.map((r) => (
                  <tr role="row" key={r.zone}>
                    <td role="cell">{r.zone}</td>
                    <td role="cell" style={{ fontSize: '0.875rem' }}>
                      {r.imported ? (
                        <>
                          <span style={{ color: '#3e8635' }}>Imported</span>
                          {(r.notes || []).map((n) => (
                            <div key={n} style={{ color: '#6a6e73' }}>{n}</div>
                          ))}
                          {r.reload && r.reload.status !== 'reloaded' && (
                            <div style={{ color: '#795600' }}>{r.reload.message}</div>
                          )}
                        </>
                      ) : (
                        <>
                          <span style={{ color: '#c9190b' }}>{r.error}</span>
                          {r.detail && (
                            <pre style={{ whiteSpace: 'pre-wrap', margin: '0.25rem 0 0',
                              fontSize: '0.8rem' }}>{r.detail}</pre>
                          )}
                        </>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </ModalBody>
      <ModalFooter>
        {step === 'review' && (
          <Button variant="primary" onClick={runImport}
            isDisabled={busy || importable.length === 0 || blocked.length > 0}>
            {busy ? 'Importing...' : `Import ${importable.length} zone(s)`}
          </Button>
        )}
        <Button variant="link" onClick={close}>
          {step === 'done' ? 'Close' : 'Cancel'}
        </Button>
      </ModalFooter>
    </Modal>
  );
};
