import { useState } from 'react';
import { API_BASE } from '../config';

export default function RegistrationDemo() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [status, setStatus] = useState('idle'); // idle, loading, error, success
  const [result, setResult] = useState(null);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!email) return;

    setStatus('loading');

    try {
      const res = await fetch(`${API_BASE}/verify-email`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email })
      });

      if (!res.ok) throw new Error('API error');

      const data = await res.json();
      setResult(data);
      
      setTimeout(() => {
        if (data.status === 'invalid' || data.status === 'suspicious') {
          setStatus('error');
        } else {
          setStatus('success');
        }
      }, 1500); // simulate processing
      
    } catch (err) {
      console.error(err);
      setStatus('error');
      setResult({ status: 'invalid' });
    }
  };

  const closeOverlay = () => {
    setStatus('idle');
    setResult(null);
  };

  return (
    <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', position: 'relative' }}>
      <div className="ambient-blobs"></div>

      <div className="glass-card" style={{ position: 'relative', zIndex: 10, width: '100%', maxWidth: '420px' }}>
        <div style={{ textAlign: 'center', marginBottom: '2rem' }}>
          <h1 style={{ fontSize: '2rem', fontWeight: 700, marginBottom: '0.5rem', fontFamily: "'Outfit', sans-serif" }}>Nexus Cloud</h1>
          <p style={{ color: 'var(--text-muted)', fontSize: '0.95rem' }}>Create your account to get started.</p>
        </div>

        <form onSubmit={handleSubmit}>
          <div style={{ marginBottom: '1.5rem' }}>
            <label style={{ display: 'block', marginBottom: '0.5rem', fontSize: '0.875rem', fontWeight: 600, color: 'var(--text-main)' }}>Email Address</label>
            <input 
              type="email" 
              placeholder="john@example.com" 
              required 
              style={{ width: '100%', padding: '0.875rem 1rem', background: 'rgba(255,255,255,0.8)', border: '1px solid rgba(0,0,0,0.1)', borderRadius: '12px', color: 'var(--text-main)', fontSize: '1rem', outline: 'none' }}
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </div>
          <div style={{ marginBottom: '1.5rem' }}>
            <label style={{ display: 'block', marginBottom: '0.5rem', fontSize: '0.875rem', fontWeight: 600, color: 'var(--text-main)' }}>Password</label>
            <input 
              type="password" 
              placeholder="••••••••" 
              required 
              style={{ width: '100%', padding: '0.875rem 1rem', background: 'rgba(255,255,255,0.8)', border: '1px solid rgba(0,0,0,0.1)', borderRadius: '12px', color: 'var(--text-main)', fontSize: '1rem', outline: 'none' }}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </div>
          <button type="submit" disabled={status === 'loading'} className="btn-primary" style={{ width: '100%', padding: '1rem', justifyContent: 'center' }}>
            Create Account
          </button>
        </form>
      </div>

      {status !== 'idle' && (
        <div style={{ position: 'fixed', top: 0, left: 0, width: '100%', height: '100%', background: 'rgba(255, 255, 255, 0.4)', backdropFilter: 'blur(8px)', zIndex: 100, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center' }}>
          
          {status === 'loading' && (
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
              <div style={{ width: '50px', height: '50px', border: '4px solid rgba(0,0,0,0.1)', borderLeftColor: 'var(--brand-primary)', borderRadius: '50%', animation: 'spin 1s linear infinite', marginBottom: '1.5rem' }}></div>
              <div style={{ fontSize: '1.25rem', fontWeight: 600, marginBottom: '0.5rem', color: 'var(--text-main)' }}>Creating Account...</div>
              <div style={{ color: 'var(--text-muted)', fontSize: '0.9rem' }}>Please wait a moment</div>
            </div>
          )}

          {(status === 'error' || status === 'success') && (
            <div className="glass-card" style={{ maxWidth: '400px', textAlign: 'center', boxShadow: '0 20px 40px rgba(0,0,0,0.1)' }}>
              
              <div style={{ fontSize: '3rem', marginBottom: '1rem' }}>
                {status === 'error' ? '❌' : '✅'}
              </div>
              <div style={{ fontSize: '1.5rem', fontWeight: 700, marginBottom: '0.5rem', color: status === 'error' ? 'var(--status-invalid)' : 'var(--status-valid)' }}>
                {status === 'error' ? 'Registration Blocked' : 'Account Created!'}
              </div>
              <div style={{ color: 'var(--text-muted)', fontSize: '0.95rem', marginBottom: '1.5rem', lineHeight: 1.5 }}>
                {status === 'error' ? 'Your email was flagged as disposable or invalid. Please use a legitimate email address.' : 'Welcome to Nexus Cloud. Please check your inbox to verify your account.'}
              </div>
              
              <button onClick={closeOverlay} className="btn-outline" style={{ width: '100%' }}>
                {status === 'error' ? 'Try Again' : 'Continue'}
              </button>
            </div>
          )}

        </div>
      )}
      <style>{`@keyframes spin { 100% { transform: rotate(360deg); } }`}</style>
    </div>
  );
}
