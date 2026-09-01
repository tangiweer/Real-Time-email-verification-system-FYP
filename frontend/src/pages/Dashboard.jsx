import { useState } from 'react';
import { API_BASE } from '../config';

export default function Dashboard() {
  const [apiKey, setApiKeyValue] = useState('');
  const saveApiKey = async () => {
    const response = await fetch(`${API_BASE}/admin/session`, { method: 'POST', credentials: 'same-origin', headers: { 'X-API-Key': apiKey } });
    if (!response.ok) { alert('Invalid API key.'); return; }
    setApiKeyValue('');
    alert('Secure administrator session created.');
  };

  return (
    <>
      <h1 className="intro-title" style={{ marginBottom: '3rem' }}>
        Enterprise <span>Verification</span> Gateway
      </h1>
      <div className="grid-container" style={{ maxWidth: '900px', marginTop: '1rem' }}>
        
        <div className="glass-card">
          <div className="console-header">
            <h3>Authentication</h3>
          </div>
          <p style={{ color: 'var(--text-muted)', marginBottom: '1rem' }}>
            Enter an administrator API key for this session. It is never embedded in the application build or displayed to other users.
          </p>
          <div style={{ display: 'flex', gap: '1rem', alignItems: 'center', background: '#f8fafc', padding: '1rem', borderRadius: '8px', border: '1px solid var(--border-color)' }}>
            <input type="password" value={apiKey} onChange={(e) => setApiKeyValue(e.target.value)} placeholder="Enter X-API-Key" style={{ flex: 1, padding: '0.65rem', border: '1px solid var(--border-color)', borderRadius: '6px' }} />
            <button className="btn-outline" style={{ padding: '0.5rem 1rem' }} onClick={saveApiKey}>
              Save
            </button>
          </div>
        </div>

        <div className="glass-card">
          <div className="console-header">
            <h3>Integration Guide</h3>
          </div>
          <p style={{ color: 'var(--text-muted)', marginBottom: '1.5rem' }}>
            Use these code snippets to integrate the real-time Verification Gateway into your application.
          </p>
          
          <div style={{ background: '#1e293b', borderRadius: '8px', overflow: 'hidden', boxShadow: '0 4px 6px -1px rgba(0, 0, 0, 0.1)' }}>
            <div style={{ display: 'flex', background: '#0f172a', padding: '0.75rem 1.5rem', borderBottom: '1px solid #334155' }}>
              <span style={{ color: '#38bdf8', fontSize: '0.85rem', fontWeight: 600, marginRight: '1.5rem', cursor: 'pointer' }}>cURL</span>
              <span style={{ color: '#94a3b8', fontSize: '0.85rem', cursor: 'pointer', marginRight: '1.5rem' }}>Python</span>
              <span style={{ color: '#94a3b8', fontSize: '0.85rem', cursor: 'pointer' }}>Node.js</span>
            </div>
            <pre style={{ padding: '1.5rem', margin: 0, overflowX: 'auto', fontFamily: '"Courier New", Courier, monospace', fontSize: '0.9rem', lineHeight: 1.6, color: '#f8fafc' }}>
<span style={{ color: '#c4b5fd' }}>curl</span> -X POST http://127.0.0.1:8000/verify-email \
  -H <span style={{ color: '#a7f3d0' }}>"X-API-Key: YOUR_API_KEY"</span> \
  -H <span style={{ color: '#a7f3d0' }}>"Content-Type: application/json"</span> \
  -d <span style={{ color: '#fde047' }}>{`'{"email": "user@example.com"}'`}</span>
            </pre>
          </div>
        </div>

      </div>
    </>
  );
}
