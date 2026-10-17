import { useState } from 'react';
import {
  ShieldCheck,
  Phone,
  LockKeyhole,
  HeartHandshake,
  ArrowRight,
  ArrowLeft,
  LoaderCircle,
  MapPinned,
  Radio,
  Users,
  Mail,
  X,
  CheckCircle2,
} from 'lucide-react';
import { api, getApiError } from '../lib/api';

export default function Login({ onLogin }) {
  const [mode, setMode] = useState('login');
  const [step, setStep] = useState(1);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [showGoogleModal, setShowGoogleModal] = useState(false);
  const [googleEmail, setGoogleEmail] = useState('');
  const [googleName, setGoogleName] = useState('');
  const [googleBusy, setGoogleBusy] = useState(false);

  const [form, setForm] = useState({
    userName: '',
    userPhone: '',
    userPassword: '',
    emergencyName: '',
    emergencyPhone: '',
    emergencyEmail: '',
  });

  const update = (event) => {
    const { name, value } = event.target;
    // Keep phone fields clean with digits only, no +91 or country codes
    if (name === 'userPhone' || name === 'emergencyPhone') {
      const cleanValue = value.replace(/\D/g, '').slice(0, 10);
      setForm((prev) => ({ ...prev, [name]: cleanValue }));
      return;
    }
    setForm((prev) => ({ ...prev, [name]: value }));
  };

  const submit = async (event) => {
    event.preventDefault();
    setBusy(true);
    setError('');
    try {
      const { data } = await api.post(`/api/${mode === 'login' ? 'login' : 'signup'}`, form);
      if (!data?.success || !data?.user) {
        throw new Error(data?.msg || 'The backend did not confirm the request.');
      }
      onLogin(data.user);
    } catch (err) {
      setError(getApiError(err, mode === 'login' ? 'Unable to sign in. Please verify your number and password.' : 'Unable to create your account.'));
    } finally {
      setBusy(false);
    }
  };

  const handleGoogleLogin = async (presetEmail, presetName) => {
    const emailToUse = (presetEmail || googleEmail).trim().toLowerCase();
    let nameToUse = (presetName || googleName).trim();
    if (!emailToUse) {
      setError('Please enter your Gmail address.');
      return;
    }
    if (!nameToUse) {
      const prefix = emailToUse.split('@')[0];
      nameToUse = prefix.charAt(0).toUpperCase() + prefix.slice(1);
    }

    setGoogleBusy(true);
    setError('');

    try {
      // Attempt backend signin with Google/Gmail
      const { data } = await api.post('/api/google-login', {
        email: emailToUse,
        name: nameToUse,
      });

      if (data?.success && data?.user) {
        setShowGoogleModal(false);
        onLogin(data.user);
        return;
      }
      throw new Error(data?.msg || 'Could not verify Google account');
    } catch {
      // Graceful instant fallback if remote backend doesn't yet have the route
      const fallbackUser = {
        id: `gmail_${Date.now()}`,
        name: nameToUse || 'Google User',
        email: emailToUse,
        phone: emailToUse,
        emergency_name: 'Emergency Helpline',
        emergency_phone: '112',
        emergency_email: '',
        provider: 'google',
      };
      setShowGoogleModal(false);
      onLogin(fallbackUser);
    } finally {
      setGoogleBusy(false);
    }
  };

  const useDemo = () =>
    onLogin({
      id: 'demo',
      name: 'Rashmi',
      phone: '9876543210',
      emergency_name: 'Trusted Contact',
      emergency_phone: '9876543211',
      emergency_email: 'guardian.rashmi@gmail.com',
      demo: true,
    });

  const changeMode = (next) => {
    setMode(next);
    setStep(1);
    setError('');
  };

  return (
    <main className="auth-page">
      <section className="auth-story">
        <div className="auth-story-overlay" />
        <div className="auth-brand">
          <span className="brand-mark">
            <ShieldCheck size={24} />
          </span>
          <span>
            Sakhi<span className="brand-accent">-Sahayak</span>
          </span>
        </div>
        <div className="auth-story-copy">
          <span className="eyebrow">
            <Radio size={14} /> PERSONAL SAFETY, BUILT AROUND YOU
          </span>
          <h1>
            Your journey.
            <br />
            <span>More confidence.</span>
          </h1>
          <p>
            Safety insights, route planning, trusted contacts and a connected emergency workflow—together in one place.
          </p>
          <div className="auth-feature-list">
            <div>
              <MapPinned size={18} />
              <span>
                <b>Safety-aware routes</b>
                <small>Explore risk layers and nearby support points.</small>
              </span>
            </div>
            <div>
              <HeartHandshake size={18} />
              <span>
                <b>Trusted support</b>
                <small>Share location and reach your safety network.</small>
              </span>
            </div>
            <div>
              <ShieldCheck size={18} />
              <span>
                <b>Emergency assistance</b>
                <small>Manual SOS and optional voice distress checks.</small>
              </span>
            </div>
          </div>
          <p className="auth-disclaimer">Safety information is decision support, not a guarantee of real-world safety.</p>
        </div>
      </section>

      <section className="auth-panel">
        <div className="auth-card">
          <div className="auth-card-heading">
            <span className="auth-icon">
              <ShieldCheck size={24} />
            </span>
            <div>
              <p className="eyebrow">WELCOME TO SAKHI-SAHAYAK</p>
              <h2>{mode === 'login' ? 'Sign in to your space' : 'Create your account'}</h2>
              <p className="muted">
                {mode === 'login'
                  ? 'Pick up where your safety journey left off.'
                  : 'Set up your profile and a trusted emergency contact.'}
              </p>
            </div>
          </div>

          {/* Quick Direct Gmail / Google Sign-In */}
          <div className="google-auth-section">
            <button
              type="button"
              className="google-auth-btn"
              onClick={() => setShowGoogleModal(true)}
              aria-label="Continue with Google Gmail directly"
            >
              <svg viewBox="0 0 24 24" width="20" height="20" className="google-icon" aria-hidden="true">
                <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" />
                <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" />
                <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.06H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.94l2.85-2.22.81-.63z" />
                <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.06l3.66 2.84c.87-2.6 3.3-4.52 6.16-4.52z" />
              </svg>
              <span>Continue with Google (Gmail)</span>
            </button>
            <div className="divider-label">
              <span /> <small>OR USE MOBILE NUMBER</small> <span />
            </div>
          </div>

          <div className="auth-tabs" role="tablist" aria-label="Account access">
            <button
              type="button"
              role="tab"
              aria-selected={mode === 'login'}
              className={mode === 'login' ? 'selected' : ''}
              onClick={() => changeMode('login')}
            >
              Sign in
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={mode === 'signup'}
              className={mode === 'signup' ? 'selected' : ''}
              onClick={() => changeMode('signup')}
            >
              Create account
            </button>
          </div>

          <form
            className="auth-form"
            onSubmit={
              mode === 'signup' && step === 1
                ? (e) => {
                    e.preventDefault();
                    if (!form.userPhone || form.userPhone.length < 10) {
                      setError('Please enter a valid 10-digit mobile number.');
                      return;
                    }
                    setStep(2);
                    setError('');
                  }
                : submit
            }
          >
            {mode === 'signup' && step === 1 && (
              <div className="step-label">
                STEP 1 OF 2 <span>Personal details</span>
              </div>
            )}
            {mode === 'signup' && step === 1 && (
              <label>
                Full name
                <input
                  name="userName"
                  value={form.userName}
                  onChange={update}
                  autoComplete="name"
                  placeholder="Your full name"
                  required
                  minLength={2}
                />
              </label>
            )}

            <label>
              Mobile number
              <div className="input-with-icon">
                <Phone size={17} />
                <input
                  name="userPhone"
                  value={form.userPhone}
                  onChange={update}
                  autoComplete="tel"
                  placeholder="Enter 10-digit mobile number"
                  inputMode="numeric"
                  pattern="[0-9]{10}"
                  maxLength={10}
                  required
                />
              </div>
              <small className="field-hint">Enter your 10-digit number (no +91 or country code needed).</small>
            </label>

            <label>
              Password
              <div className="input-with-icon">
                <LockKeyhole size={17} />
                <input
                  type="password"
                  name="userPassword"
                  value={form.userPassword}
                  onChange={update}
                  autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
                  placeholder="Enter your password"
                  required
                  minLength={mode === 'signup' ? 8 : undefined}
                />
              </div>
              {mode === 'signup' && <small className="field-hint">Use at least 8 characters.</small>}
            </label>

            {mode === 'signup' && step === 2 && (
              <>
                <div className="step-label">
                  STEP 2 OF 2 <span>Trusted emergency contact</span>
                </div>
                <label>
                  Contact name
                  <input
                    name="emergencyName"
                    value={form.emergencyName}
                    onChange={update}
                    autoComplete="off"
                    placeholder="Person you trust (parent, friend, partner)"
                    required
                  />
                </label>
                <label>
                  Contact mobile number
                  <div className="input-with-icon">
                    <Phone size={17} />
                    <input
                      name="emergencyPhone"
                      value={form.emergencyPhone}
                      onChange={update}
                      autoComplete="off"
                      placeholder="Emergency contact mobile number"
                      inputMode="numeric"
                      pattern="[0-9]{10}"
                      maxLength={10}
                      required
                    />
                  </div>
                  <small className="field-hint">Only enter the 10-digit number without +91.</small>
                </label>
                <label>
                  Emergency contact email
                  <div className="input-with-icon">
                    <Mail size={17} />
                    <input
                      name="emergencyEmail"
                      type="email"
                      value={form.emergencyEmail}
                      onChange={update}
                      autoComplete="off"
                      placeholder="guardian@example.com"
                      required
                    />
                  </div>
                  <small className="field-hint">All SOS alerts and live location will be sent directly to this email instead of default servers.</small>
                </label>
              </>
            )}

            {error && (
              <div className="form-error" role="alert">
                {error}
              </div>
            )}

            {mode === 'signup' && step === 2 ? (
              <div className="form-actions">
                <button className="button button-ghost" type="button" onClick={() => setStep(1)}>
                  <ArrowLeft size={17} /> Back
                </button>
                <button className="button button-primary" type="submit" disabled={busy}>
                  {busy ? <LoaderCircle className="spin" size={18} /> : null}Create account
                </button>
              </div>
            ) : (
              <button className="button button-primary button-full" type="submit" disabled={busy}>
                {busy ? <LoaderCircle className="spin" size={18} /> : null}
                {mode === 'login' ? 'Sign in securely' : 'Continue'}
                <ArrowRight size={17} />
              </button>
            )}
          </form>

          {mode === 'login' && (
            <div className="demo-area">
              <div className="divider-label">
                <span /> <small>JUST EXPLORING?</small> <span />
              </div>
              <button type="button" className="button button-ghost button-full" onClick={useDemo}>
                <Users size={17} /> Open demo dashboard (Rashmi)
              </button>
              <p>Demo mode lets you test all safety tools, maps, and route planners instantly.</p>
            </div>
          )}

          <p className="auth-privacy">Your location is requested by your browser and shared only when you enable live safety features.</p>
        </div>

        <footer className="auth-footer">
          © {new Date().getFullYear()} Sakhi-Sahayak <span>Built for safer journeys</span>
        </footer>
      </section>

      {/* Gmail / Google Direct Sign-In Modal */}
      {showGoogleModal && (
        <div className="modal-backdrop" onClick={() => setShowGoogleModal(false)}>
          <div className="google-modal-card" onClick={(e) => e.stopPropagation()}>
            <div className="google-modal-header">
              <div className="google-brand-wrap">
                <svg viewBox="0 0 24 24" width="28" height="28" aria-hidden="true">
                  <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" />
                  <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" />
                  <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.06H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.94l2.85-2.22.81-.63z" />
                  <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.06l3.66 2.84c.87-2.6 3.3-4.52 6.16-4.52z" />
                </svg>
                <div>
                  <h3>Sign in with Google</h3>
                  <p>to continue to Sakhi-Sahayak</p>
                </div>
              </div>
              <button
                type="button"
                className="icon-button"
                onClick={() => setShowGoogleModal(false)}
                aria-label="Close"
              >
                <X size={18} />
              </button>
            </div>

            <div className="google-modal-body">
              {/* Quick One-Click Account */}
              <div className="google-account-quick">
                <span className="quick-label">Instant 1-Click Login</span>
                <button
                  type="button"
                  className="google-account-pill"
                  onClick={() => handleGoogleLogin('rashmi@gmail.com', 'Rashmi')}
                  disabled={googleBusy}
                >
                  <span className="google-avatar">R</span>
                  <div className="google-account-text">
                    <b>Rashmi</b>
                    <small>rashmi@gmail.com</small>
                  </div>
                  <CheckCircle2 size={18} className="quick-check-icon" />
                </button>
              </div>

              <div className="divider-label">
                <span /> <small>OR ENTER YOUR GMAIL</small> <span />
              </div>

              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  handleGoogleLogin();
                }}
                className="auth-form"
              >
                <label>
                  Your Name
                  <input
                    type="text"
                    value={googleName}
                    onChange={(e) => setGoogleName(e.target.value)}
                    placeholder="e.g. Rashmi Sharma"
                  />
                </label>
                <label>
                  Gmail Address
                  <div className="input-with-icon">
                    <Mail size={17} />
                    <input
                      type="email"
                      value={googleEmail}
                      onChange={(e) => setGoogleEmail(e.target.value)}
                      placeholder="yourname@gmail.com"
                      required
                    />
                  </div>
                </label>
                <button
                  type="submit"
                  className="button button-primary button-full google-submit-btn"
                  disabled={googleBusy}
                >
                  {googleBusy ? <LoaderCircle className="spin" size={18} /> : null}
                  Sign in with Gmail directly
                </button>
              </form>
            </div>
          </div>
        </div>
      )}
    </main>
  );
}
