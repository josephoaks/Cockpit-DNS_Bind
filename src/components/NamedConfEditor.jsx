// =============================================================================
// src/components/NamedConfEditor.jsx
//
// Full-screen terminal-style editor for the live /etc/named.conf.
//
// The file is shown verbatim, comments included. A stock SUSE named.conf is
// mostly documentation -- and carries commented-out settings people uncomment
// later -- so stripping comments for display would destroy them on save.
//
// Save path is snapshot -> write -> named-checkconf -> restore on failure ->
// rndc reconfig, all handled by the backend.
// =============================================================================

import React, { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Alert, Button, Spinner } from '@patternfly/react-core';
import { spawnBackend, spawnBackendInput } from '../utils/backend';

const KEYS = [
  ['F2', 'Save'],
  ['F5', 'Check'],
  ['F3', 'Revert'],
  ['F10', 'Exit'],
  ['Tab', 'Indent'],
];

// named-checkconf and the schema linter both report "line N"; pull those out so
// the gutter can mark them.
const flaggedLines = (lint) => {
  if (!lint) return new Set();
  const out = new Set();
  for (const msg of lint.schema || []) {
    const m = /^line (\d+):/.exec(msg);
    if (m) out.add(Number(m[1]));
  }
  if (!lint.checkconfOk && lint.checkconf) {
    for (const m of lint.checkconf.matchAll(/named\.conf:(\d+)/g)) {
      out.add(Number(m[1]));
    }
  }
  return out;
};

export const NamedConfEditor = ({ onClose, onSaved }) => {
  const [original, setOriginal] = useState('');
  const [text, setText] = useState('');
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [lint, setLint] = useState(null);
  const [saved, setSaved] = useState(null);
  const [exitPrompt, setExitPrompt] = useState(false);
  const [mounted, setMounted] = useState(false);

  const taRef = useRef(null);
  const gutterRef = useRef(null);

  useEffect(() => { setMounted(true); }, []);

  useEffect(() => {
    const load = async () => {
      try {
        const result = JSON.parse(await spawnBackend(['read-named-conf']));
        if (result.error) {
          setError(result.error);
          return;
        }
        setOriginal(result.content);
        setText(result.content);
      } catch (err) {
        setError('Could not read named.conf: ' + err.message);
      } finally {
        setLoading(false);
      }
    };
    load();
  }, []);

  useEffect(() => { if (!loading) taRef.current?.focus(); }, [loading]);

  const dirty = text !== original;

  const runLint = async (buffer) => {
    setBusy(true);
    setError(null);
    try {
      setLint(JSON.parse(await spawnBackendInput(['lint-named-conf'], buffer ?? text)));
    } catch (err) {
      setError('Check failed: ' + err.message);
    } finally {
      setBusy(false);
    }
  };

  const save = async () => {
    setBusy(true);
    setError(null);
    setSaved(null);
    try {
      const result = JSON.parse(await spawnBackendInput(['write-named-conf'], text));
      if (result.error) {
        setError(result.error);
        // The write was rejected and rolled back, so show where.
        await runLint(text);
        return;
      }
      setOriginal(text);
      setLint(null);
      setSaved(result);
      onSaved();
    } catch (err) {
      setError('Save failed: ' + err.message);
    } finally {
      setBusy(false);
    }
  };

  const attemptExit = () => (dirty ? setExitPrompt(true) : onClose());

  const handleKeyDown = (e) => {
    if (e.key === 'F2') { e.preventDefault(); if (dirty && !busy) save(); }
    if (e.key === 'F5') { e.preventDefault(); if (!busy) runLint(); }
    if (e.key === 'F3') { e.preventDefault(); setText(original); setLint(null); }
    if (e.key === 'F10') { e.preventDefault(); attemptExit(); }
    if (e.key === 'Tab') {
      e.preventDefault();
      const ta = taRef.current;
      const { selectionStart: s, selectionEnd: end } = ta;
      // named.conf is tab-indented; inserting spaces would fight the file.
      setText(`${text.slice(0, s)}\t${text.slice(end)}`);
      requestAnimationFrame(() => { ta.selectionStart = ta.selectionEnd = s + 1; });
    }
  };

  // Keep the line numbers aligned with the text as it scrolls.
  const handleScroll = () => {
    if (gutterRef.current && taRef.current) {
      gutterRef.current.scrollTop = taRef.current.scrollTop;
    }
  };

  const lines = text.split('\n');
  const flagged = flaggedLines(lint);
  const lintClean = lint && lint.checkconfOk && lint.schema.length === 0;

  if (!mounted) return null;

  return createPortal(
    <div className="dnsbind-editor-backdrop">
      <div className="dnsbind-editor-window">
        <div className="dnsbind-editor-titlebar">
          <span className="dnsbind-editor-titlebar__path">/etc/named.conf</span>
          {dirty && <span className="dnsbind-editor-titlebar__modified">Modified</span>}
          {busy && <Spinner size="sm" />}
          <span className="dnsbind-editor-titlebar__lines">{lines.length} lines</span>
        </div>

        <div className="dnsbind-editor-notices">
          <Alert variant="danger" isInline title="Do not edit zone statements here"
            style={{ marginBottom: '0.75rem' }}>
            <p style={{ fontWeight: 'bold' }}>
              Zone blocks are managed from the DNS Zones page. Editing them here can
              conflict with changes the plugin makes and leave named unable to start.
              Use this editor for options, logging, ACLs and includes only.
            </p>
          </Alert>

          {error && (
            <Alert variant="danger" isInline title="named.conf was not changed"
              style={{ marginBottom: '0.75rem' }}>
              <pre style={{ whiteSpace: 'pre-wrap', margin: 0, fontSize: '0.8rem' }}>{error}</pre>
            </Alert>
          )}

          {saved && (
            <Alert variant="success" isInline title="named.conf saved"
              style={{ marginBottom: '0.75rem' }}>
              <p>Previous version backed up to <code>{saved.backup}</code>.</p>
              {saved.reload && saved.reload.status !== 'reloaded' && (
                <p>{saved.reload.message}</p>
              )}
              {(saved.warnings || []).map((w) => <p key={w}>{w}</p>)}
            </Alert>
          )}

          {lint && (
            <Alert
              variant={lintClean ? 'success' : 'warning'}
              isInline
              title={lintClean ? 'No problems found' : 'Problems found'}
              style={{ marginBottom: '0.75rem' }}
            >
              {(lint.schema || []).map((p) => <div key={p}>{p}</div>)}
              {!lint.checkconfOk && (
                <pre style={{ whiteSpace: 'pre-wrap', margin: '0.5rem 0 0', fontSize: '0.8rem' }}>
                  {lint.checkconf}
                </pre>
              )}
            </Alert>
          )}
        </div>

        <div className="dnsbind-editor-body">
          {loading ? (
            <div style={{ padding: '2rem' }}><Spinner size="lg" /></div>
          ) : (
            <>
              <div className="dnsbind-editor-gutter" ref={gutterRef}>
                {lines.map((_, i) => (
                  <div
                    key={i}
                    className={`dnsbind-editor-gutter__line${flagged.has(i + 1) ? ' is-flagged' : ''}`}
                  >
                    {i + 1}
                  </div>
                ))}
              </div>
              <textarea
                ref={taRef}
                className="dnsbind-editor-textarea"
                value={text}
                onChange={(e) => setText(e.target.value)}
                onKeyDown={handleKeyDown}
                onScroll={handleScroll}
                spellCheck={false}
                wrap="off"
              />
            </>
          )}
        </div>

        <div className="dnsbind-editor-keys">
          {KEYS.map(([key, action]) => (
            <span key={key} className="dnsbind-editor-keys__entry">
              <span className="dnsbind-editor-keys__key">{key}</span>{action}
            </span>
          ))}
          <span style={{ marginLeft: 'auto', display: 'flex', gap: '0.5rem' }}>
            <Button variant="primary" size="sm" onClick={save} isDisabled={busy || !dirty}>
              Save
            </Button>
            <Button variant="secondary" size="sm" onClick={() => runLint()} isDisabled={busy}>
              Check
            </Button>
            <Button variant="secondary" size="sm" isDisabled={busy || !dirty}
              onClick={() => { setText(original); setLint(null); }}>
              Revert
            </Button>
            <Button variant="link" size="sm" onClick={attemptExit}>Exit</Button>
          </span>
        </div>

        {exitPrompt && (
          <div className="dnsbind-editor-prompt">
            <span>Unsaved changes to named.conf. Exit anyway?</span>
            <Button variant="danger" size="sm" onClick={onClose}>Discard changes</Button>
            <Button variant="secondary" size="sm" onClick={() => setExitPrompt(false)}>
              Keep editing
            </Button>
          </div>
        )}
      </div>
    </div>,
    document.body
  );
};
