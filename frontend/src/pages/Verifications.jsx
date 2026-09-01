import { useState } from 'react';
import { Download } from 'lucide-react';
import { API_BASE, apiHeaders, apiFetch } from '../config';

export default function Verifications() {
  const [email, setEmail] = useState('');
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  const [history, setHistory] = useState([]);

  const verifyEmail = async () => {
    if (!email) return;
    
    setLoading(true);
    setResult(null);

    try {
      const response = await apiFetch(`${API_BASE}/verify-email`, {
        method: 'POST',
        headers: apiHeaders({ 'Content-Type': 'application/json' }),
        body: JSON.stringify({ email })
      });
      
      let data;
      try {
        data = await response.json();
      } catch {
        throw new Error('Server returned an invalid response (not JSON). Please check the backend connection.');
      }

      if (!response.ok) {
        if (response.status === 401) {
          alert('Administrator access is required. Go to the Dashboard and save your API key to start an admin session.');
          return;
        }
        const errorMsg = data.error || data.detail || 'Verification request failed.';
        alert(`Error: ${errorMsg}`);
        return;
      }

      setResult(data);
      
      setHistory(prev => [{
        email: data.email,
        status: data.status,
        confidence: data.confidence,
        failed_layer: data.failed_layer,
        checkedAt: new Date().toLocaleTimeString(),
      }, ...prev].slice(0, 10)); // Keep last 10
      
    } catch (err) {
      console.error(err);
      alert(err.message || 'Verification failed');
    } finally {
      setLoading(false);
    }
  };

  const exportCSV = () => {
    if (history.length === 0) return;
    const csvContent = "data:text/csv;charset=utf-8," 
      + "Email,Status,Confidence,FailedLayer,CheckedAt\n"
      + history.map(e => `${e.email},${e.status},${e.confidence},${e.failed_layer || 'None'},${e.checkedAt}`).join("\n");
    const encodedUri = encodeURI(csvContent);
    const link = document.createElement("a");
    link.setAttribute("href", encodedUri);
    link.setAttribute("download", "verification_history.csv");
    document.body.appendChild(link);
    link.click();
    link.remove();
  };

  // Helpers for styling
  const getStatusStyle = (status) => {
    switch (status) {
      case 'valid': return { color: 'var(--status-valid)', bg: 'var(--status-valid-bg)' };
      case 'invalid': return { color: 'var(--status-invalid)', bg: 'var(--status-invalid-bg)' };
      case 'suspicious': return { color: 'var(--status-warning)', bg: 'var(--status-warning-bg)' };
      default: return { color: 'var(--text-muted)', bg: 'rgba(0,0,0,0.05)' };
    }
  };

  return (
    <>
      <div className="grid-container">
        <h1 className="intro-title">Validate every email.<br/>Protect <span>deliverability</span>.</h1>

        <div className="glass-card">
          <div className="console-header">
            <h3>Verification Console</h3>
          </div>
          <p style={{ fontSize: '0.875rem', color: 'var(--text-muted)', marginBottom: '1rem' }}>
            Enter an email address to run the verification pipeline and get a clear recommendation.
          </p>

          <div className="input-group">
            <input 
              type="email" 
              placeholder="marketing.lead@company.com" 
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && verifyEmail()}
            />
            <button className="btn-primary" onClick={verifyEmail} disabled={loading}>
              {loading ? 'Verifying...' : 'Verify Now'}
            </button>
          </div>

          {result && (
            <>
              <div className="result-banner active" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', background: 'rgba(255,255,255,0.8)', border: '1px solid rgba(255,255,255,0.6)', borderRadius: '16px', padding: '1.5rem', marginBottom: '2rem', boxShadow: '0 4px 15px rgba(0,0,0,0.03)' }}>
                <div className="result-status-main" style={{ display: 'flex', alignItems: 'center', gap: '1.25rem' }}>
                  <div className={`status-circle ${result.status}`} style={{ width: '56px', height: '56px', borderRadius: '50%', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '1.75rem', color: 'white', background: getStatusStyle(result.status).bg }}>
                    {result.status === 'valid' ? '✓' : result.status === 'invalid' ? '✗' : '!'}
                  </div>
                  <div className="result-text-block">
                    <div className="label" style={{ fontSize: '0.8rem', color: 'var(--text-muted)', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '0.25rem' }}>Result</div>
                    <div className="value" style={{ fontSize: '1.75rem', fontWeight: 800, textTransform: 'capitalize', letterSpacing: '-0.02em', color: getStatusStyle(result.status).color }}>{result.status}</div>
                  </div>
                </div>
                <div className="confidence-block" style={{ textAlign: 'right' }}>
                  <div className="label" style={{ fontSize: '0.8rem', color: 'var(--text-muted)', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '0.25rem' }}>Confidence Score</div>
                  <div className="value" style={{ fontSize: '2rem', fontWeight: 800, color: 'var(--text-main)', letterSpacing: '-0.02em' }}>{Math.round(result.confidence * 100)}%</div>
                </div>
              </div>

              <div className="pipeline-layers active" style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
                {Object.entries(result.execution_times || {}).map(([layer, time]) => (
                  <div key={layer} className="layer-row" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '1.25rem', border: '1px solid rgba(255,255,255,0.6)', borderRadius: '16px', background: 'rgba(255,255,255,0.8)' }}>
                    <div className="layer-info" style={{ display: 'flex', alignItems: 'center', gap: '1.25rem' }}>
                      <div className="layer-icon" style={{ width: '44px', height: '44px', background: 'rgba(99, 102, 241, 0.08)', color: 'var(--brand-primary)', borderRadius: '12px', display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 600 }}>{layer.substring(0, 2).toUpperCase()}</div>
                      <div className="layer-text">
                        <h4 style={{ fontSize: '1rem', fontWeight: 600, color: 'var(--text-main)', textTransform: 'capitalize' }}>{layer.replace('_', ' ')}</h4>
                        <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginTop: '0.25rem' }}>Execution time: {time}ms</p>
                      </div>
                    </div>
                    <div className="layer-status" style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '0.95rem', fontWeight: 600, padding: '0.5rem 1rem', borderRadius: '999px', background: result.failed_layer === layer ? 'var(--status-invalid-bg)' : 'var(--status-valid-bg)', color: result.failed_layer === layer ? 'var(--status-invalid)' : 'var(--status-valid)' }}>
                      {result.failed_layer === layer ? 'Failed' : 'Passed'}
                    </div>
                  </div>
                ))}
              </div>
            </>
          )}
        </div>

        <div className="glass-card">
          <div className="console-header">
            <h3>Recent Verifications</h3>
            <button className="badge" style={{ background: 'var(--brand-primary)', color: 'white', border: 'none', cursor: 'pointer', padding: '0.35rem 0.85rem', borderRadius: '999px', fontSize: '0.75rem', fontWeight: 700 }} onClick={exportCSV}>
              <Download size={14} style={{ marginRight: '4px', display: 'inline-block', verticalAlign: 'middle' }}/> Export Report (CSV)
            </button>
          </div>
          <div className="table-responsive" style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'separate', borderSpacing: 0, textAlign: 'left' }}>
              <thead>
                <tr>
                  <th style={{ padding: '1.25rem 1rem', fontSize: '0.75rem', textTransform: 'uppercase', color: 'var(--text-muted)', borderBottom: '1px solid var(--border-color)' }}>Email Address</th>
                  <th style={{ padding: '1.25rem 1rem', fontSize: '0.75rem', textTransform: 'uppercase', color: 'var(--text-muted)', borderBottom: '1px solid var(--border-color)' }}>Result</th>
                  <th style={{ padding: '1.25rem 1rem', fontSize: '0.75rem', textTransform: 'uppercase', color: 'var(--text-muted)', borderBottom: '1px solid var(--border-color)' }}>Confidence</th>
                  <th style={{ padding: '1.25rem 1rem', fontSize: '0.75rem', textTransform: 'uppercase', color: 'var(--text-muted)', borderBottom: '1px solid var(--border-color)' }}>Checked At</th>
                </tr>
              </thead>
              <tbody>
                {history.length === 0 ? (
                  <tr>
                    <td colSpan="4" style={{ textAlign: 'center', color: 'var(--text-muted)', padding: '2rem' }}>No verifications yet this session. Enter an email above to start.</td>
                  </tr>
                ) : (
                  history.map((h, i) => (
                    <tr key={i}>
                      <td style={{ padding: '1.25rem 1rem', fontSize: '0.95rem', borderBottom: '1px solid rgba(0,0,0,0.05)', color: 'var(--text-main)' }}>{h.email}</td>
                      <td style={{ padding: '1.25rem 1rem', fontSize: '0.95rem', borderBottom: '1px solid rgba(0,0,0,0.05)' }}>
                        <span className="badge" style={{ ...getStatusStyle(h.status), padding: '0.35rem 0.85rem', borderRadius: '999px', fontSize: '0.75rem', fontWeight: 700 }}>
                          {h.status}
                        </span>
                      </td>
                      <td style={{ padding: '1.25rem 1rem', fontSize: '0.95rem', borderBottom: '1px solid rgba(0,0,0,0.05)', color: 'var(--text-main)' }}>{Math.round(h.confidence * 100)}%</td>
                      <td style={{ padding: '1.25rem 1rem', fontSize: '0.95rem', borderBottom: '1px solid rgba(0,0,0,0.05)', color: 'var(--text-muted)' }}>{h.checkedAt}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </>
  );
}
