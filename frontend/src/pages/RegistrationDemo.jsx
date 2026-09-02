import { useState } from 'react';
import { API_BASE } from '../config';

export default function RegistrationDemo() {
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [status, setStatus] = useState('idle');
  const [message, setMessage] = useState('');

  const handleSubmit = async (event) => {
    event.preventDefault();
    setMessage('');

    if (password !== confirmPassword) {
      setMessage('Passwords do not match.');
      return;
    }

    setStatus('loading');
    try {
      const response = await fetch(`${API_BASE}/register`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, email, password }),
      });
      const data = await response.json().catch(() => ({}));
      setMessage(response.ok
        ? (data.message || 'Registration successful.')
        : (response.status === 409 ? 'An account with this email already exists.' : 'Registration failed. Please try again.'));
    } catch {
      setMessage('Unable to connect. Please try again.');
    } finally {
      setStatus('idle');
    }
  };

  return (
    <main className="registration-page">
      <form className="simple-registration-form" onSubmit={handleSubmit}>
        <h1>Register</h1>
        <label><span><b aria-hidden="true">*</b> Name</span><input type="text" autoComplete="name" value={name} onChange={(event) => setName(event.target.value)} required disabled={status === 'loading'} /></label>
        <label><span><b aria-hidden="true">*</b> Email</span><input type="email" autoComplete="email" value={email} onChange={(event) => setEmail(event.target.value)} required disabled={status === 'loading'} /></label>
        <label><span><b aria-hidden="true">*</b> Password</span><input type="password" autoComplete="new-password" value={password} onChange={(event) => setPassword(event.target.value)} required disabled={status === 'loading'} /></label>
        <label><span><b aria-hidden="true">*</b> Confirm password</span><input type="password" autoComplete="new-password" value={confirmPassword} onChange={(event) => setConfirmPassword(event.target.value)} required disabled={status === 'loading'} /></label>
        <div className="simple-registration-divider" />
        {message && <p className="simple-registration-message" role="status">{message}</p>}
        <button type="submit" disabled={status === 'loading'}>{status === 'loading' ? 'Registering…' : 'Register'}</button>
      </form>
    </main>
  );
}
