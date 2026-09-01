import { useEffect, useState } from 'react';
import { CheckCircle2, Eye, EyeOff, LockKeyhole, Mail, UserRound, XCircle } from 'lucide-react';
import { API_BASE } from '../config';

const progressMessages = ['Checking your details…', 'Keeping your account secure…', 'Preparing your account…'];

export default function RegistrationDemo() {
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [status, setStatus] = useState('idle');
  const [progressIndex, setProgressIndex] = useState(0);
  const [outcome, setOutcome] = useState(null);

  useEffect(() => {
    if (status !== 'loading') return undefined;
    const timer = window.setInterval(() => setProgressIndex((current) => Math.min(current + 1, progressMessages.length - 1)), 900);
    return () => window.clearInterval(timer);
  }, [status]);

  const handleSubmit = async (event) => {
    event.preventDefault();
    if (!name.trim() || !email.trim() || password.length < 12) return;
    setStatus('loading');
    setProgressIndex(0);
    setOutcome(null);
    try {
      const response = await fetch(`${API_BASE}/register`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name, email, password }) });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        setOutcome({ type: 'error', title: response.status === 409 ? 'Account already exists' : 'We couldn’t create your account', message: response.status === 409 ? 'Try signing in, or use a different email address.' : 'Please check your details and try again. If the problem continues, contact support.' });
      } else {
        const needsConfirmation = data.message?.toLowerCase().includes('check your inbox');
        setOutcome({ type: 'success', title: needsConfirmation ? 'Check your inbox' : 'Your account is ready', message: needsConfirmation ? 'We sent a confirmation link to your email address. Open it to finish setting up your account.' : 'Your email has been confirmed and your account is ready to use.' });
      }
    } catch {
      setOutcome({ type: 'error', title: 'Connection problem', message: 'We could not reach the service. Please try again in a moment.' });
    } finally {
      setStatus('complete');
    }
  };

  const tryAgain = () => { setStatus('idle'); setOutcome(null); };

  return (
    <main className="registration-page">
      <div className="registration-backdrop" />
      <section className="registration-shell" aria-labelledby="registration-title">
        <div className="registration-intro">
          <p className="registration-eyebrow">Create your account</p>
          <p>Join in less than a minute. We’ll help keep your account secure from the start.</p>
          <div className="registration-benefits" aria-label="Registration benefits">
            <span><CheckCircle2 size={17} aria-hidden="true" /> Secure account setup</span>
            <span><CheckCircle2 size={17} aria-hidden="true" /> Clear next steps</span>
            <span><CheckCircle2 size={17} aria-hidden="true" /> No unwanted emails</span>
          </div>
        </div>

        <div className="registration-card">
          <div className="registration-card-heading"><h2>Get started</h2><p>Enter your details below.</p></div>
          <form onSubmit={handleSubmit} noValidate>
            <label className="registration-field"><span>Full name</span><div className="registration-input-wrap"><UserRound size={19} aria-hidden="true" /><input type="text" autoComplete="name" placeholder="Jane Smith" value={name} onChange={(event) => setName(event.target.value)} required maxLength="120" disabled={status === 'loading'} /></div></label>
            <label className="registration-field"><span>Email address</span><div className="registration-input-wrap"><Mail size={19} aria-hidden="true" /><input type="email" autoComplete="email" placeholder="jane@example.com" value={email} onChange={(event) => setEmail(event.target.value)} required disabled={status === 'loading'} /></div></label>
            <label className="registration-field"><span>Password</span><div className="registration-input-wrap"><LockKeyhole size={19} aria-hidden="true" /><input type={showPassword ? 'text' : 'password'} autoComplete="new-password" placeholder="At least 12 characters" value={password} onChange={(event) => setPassword(event.target.value)} required minLength="12" disabled={status === 'loading'} /><button type="button" className="password-toggle" onClick={() => setShowPassword((value) => !value)} aria-label={showPassword ? 'Hide password' : 'Show password'}>{showPassword ? <EyeOff size={18} /> : <Eye size={18} />}</button></div><small>Use at least 12 characters.</small></label>
            <button className="registration-submit" type="submit" disabled={status === 'loading'}>{status === 'loading' ? 'Creating your account…' : 'Create account'}</button>
          </form>
          <p className="registration-terms">By continuing, you agree to our Terms of Service and Privacy Notice.</p>
        </div>
      </section>

      {status === 'loading' && <div className="registration-modal" role="status" aria-live="polite"><div className="registration-modal-card"><div className="registration-spinner" aria-hidden="true" /><h2>Creating your account</h2><p>{progressMessages[progressIndex]}</p><div className="registration-progress" aria-hidden="true"><span style={{ width: `${((progressIndex + 1) / progressMessages.length) * 100}%` }} /></div></div></div>}
      {outcome && <div className="registration-modal" role="dialog" aria-modal="true" aria-labelledby="outcome-title"><div className="registration-modal-card">{outcome.type === 'success' ? <CheckCircle2 className="outcome-success" size={48} aria-hidden="true" /> : <XCircle className="outcome-error" size={48} aria-hidden="true" />}<h2 id="outcome-title">{outcome.title}</h2><p>{outcome.message}</p><button className="registration-submit" onClick={tryAgain}>{outcome.type === 'success' ? 'Continue' : 'Try again'}</button></div></div>}
    </main>
  );
}
