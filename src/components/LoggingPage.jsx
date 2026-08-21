// =============================================================================
// src/components/LoggingPage.jsx
//
// BIND logging, to syslog only.
//
// Log records on a real deployment are either forwarded somewhere central or
// kept by the local journal; neither needs BIND managing its own files,
// rotation and disk budget. Restricting this to syslog removes that whole
// surface, and the raw named.conf editor remains available for anything
// unusual.
// =============================================================================

import React, { useEffect, useState } from 'react';
import {
  Alert,
  Button,
  Checkbox,
  PageSection,
  Spinner,
  Title,
} from '@patternfly/react-core';
import { spawnBackend } from '../utils/backend';

const OFF = 'off';

export const LoggingPage = () => {
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [saved, setSaved] = useState(false);
  const [config, setConfig] = useState(null);
  const [enabled, setEnabled] = useState(false);
  const [facility, setFacility] = useState('daemon');
  const [categories, setCategories] = useState({});

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = JSON.parse(await spawnBackend(['read-logging']));
      if (data.error) {
        setError(data.error);
        return;
      }
      setConfig(data);
      setEnabled(data.enabled);
      setFacility(data.facility);
      setCategories(data.categories || {});
    } catch (err) {
      setError('Could not read the logging configuration: ' + err.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const setCategory = (cat, sev) => {
    const next = { ...categories };
    if (sev === OFF) delete next[cat];
    else next[cat] = sev;
    setCategories(next);
  };

  const save = async () => {
    setBusy(true);
    setError(null);
    setSaved(false);
    try {
      const payload = { enabled, facility, categories };
      const res = JSON.parse(await spawnBackend(['write-logging', JSON.stringify(payload)]));
      if (res.error) {
        setError(res.error);
        return;
      }
      setSaved(true);
      await load();
    } catch (err) {
      setError('Save failed: ' + err.message);
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

  const unmanaged = config && config.enabled && !config.managed;

  return (
    <PageSection padding={{ default: 'padding' }}>
      <Title headingLevel="h2" size="lg" style={{ marginBottom: '0.5rem' }}>
        Logging
      </Title>
      <p style={{ fontSize: '0.875rem', color: '#6a6e73', marginBottom: '1rem' }}>
        Selected categories are sent to syslog. Anything not listed here keeps
        BIND&apos;s own default, which is to log it to the daemon facility.
      </p>

      {error && (
        <Alert variant="danger" isInline title="Nothing was changed"
          style={{ marginBottom: '1rem' }}
          actionClose={<Button variant="plain" onClick={() => setError(null)}>&times;</Button>}>
          <pre style={{ whiteSpace: 'pre-wrap', margin: 0, fontSize: '0.8rem' }}>{error}</pre>
        </Alert>
      )}

      {saved && (
        <Alert variant="success" isInline title="Logging configuration saved"
          style={{ marginBottom: '1rem' }}
          actionClose={<Button variant="plain" onClick={() => setSaved(false)}>&times;</Button>} />
      )}

      {unmanaged && (
        <Alert variant="warning" isInline
          title="The existing logging block was not written by this page"
          style={{ marginBottom: '1rem' }}>
          <p>
            It uses channels this page cannot represent, such as logging to a file.
            Saving here would replace it. Edit it directly under DNS Zones &gt; Edit
            named.conf if you want to keep it.
          </p>
          {config.raw && (
            <pre style={{ whiteSpace: 'pre-wrap', marginTop: '0.5rem',
              fontSize: '0.75rem' }}>{config.raw}</pre>
          )}
        </Alert>
      )}

      <div style={{ marginBottom: '1rem' }}>
        <Checkbox
          id="logging-enabled"
          label="Send BIND log records to syslog"
          isChecked={enabled}
          onChange={(event, checked) => setEnabled(checked)}
        />
      </div>

      {enabled && (
        <>
          <div style={{ marginBottom: '1.5rem', maxWidth: '20rem' }}>
            <label htmlFor="logging-facility" style={{ display: 'block',
              fontSize: '0.875rem', marginBottom: '0.25rem' }}>
              Syslog facility
            </label>
            <select id="logging-facility" className="pf-v6-c-form-control"
              value={facility} onChange={(e) => setFacility(e.target.value)}>
              {(config.facilities || []).map((f) => (
                <option key={f} value={f}>{f}</option>
              ))}
            </select>
            <p style={{ fontSize: '0.8rem', color: '#6a6e73', marginTop: '0.25rem' }}>
              A local facility makes it easier to route BIND records separately when
              forwarding to a central collector.
            </p>
          </div>

          <table className="pf-v6-c-table pf-m-compact" role="grid"
            aria-label="Logging categories" style={{ width: '100%', tableLayout: 'fixed' }}>
            <colgroup>
              <col style={{ width: '12rem' }} />
              <col />
              <col style={{ width: '11rem' }} />
            </colgroup>
            <thead>
              <tr role="row">
                <th role="columnheader" scope="col">Category</th>
                <th role="columnheader" scope="col">Logs</th>
                <th role="columnheader" scope="col">Severity</th>
              </tr>
            </thead>
            <tbody>
              {(config.available || []).map(([cat, description]) => (
                <tr role="row" key={cat}>
                  <td role="cell"><code>{cat}</code></td>
                  <td role="cell" style={{ fontSize: '0.875rem', color: '#6a6e73' }}>
                    {description}
                  </td>
                  <td role="cell">
                    <select
                      className="pf-v6-c-form-control"
                      aria-label={`Severity for ${cat}`}
                      value={categories[cat] || OFF}
                      onChange={(e) => setCategory(cat, e.target.value)}
                    >
                      <option value={OFF}>Not logged</option>
                      {(config.severities || []).map((sev) => (
                        <option key={sev} value={sev}>{sev}</option>
                      ))}
                    </select>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}

      <div style={{ marginTop: '1.5rem' }}>
        <Button variant="primary" onClick={save} isDisabled={busy}>
          {busy ? 'Saving...' : 'Save Changes'}
        </Button>
      </div>
    </PageSection>
  );
};
