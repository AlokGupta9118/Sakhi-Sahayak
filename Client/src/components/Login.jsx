import { useState } from 'react';
import { ShieldCheck, Phone, LockKeyhole, HeartHandshake, ArrowRight, ArrowLeft, LoaderCircle, MapPinned, Radio, Users } from 'lucide-react';
import { api, getApiError } from '../lib/api';

export default function Login({ onLogin }) {
  const [mode, setMode] = useState('login');
  const [step, setStep] = useState(1);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [form, setForm] = useState({ userName: '', userPhone: '', userPassword: '', emergencyName: '', emergencyPhone: '' });
  const update = (event) => setForm((prev) => ({ ...prev, [event.target.name]: event.target.value }));

  const submit = async (event) => {
    event.preventDefault();
    setBusy(true); setError('');
    try {
      const { data } = await api.post(`/api/${mode === 'login' ? 'login' : 'signup'}`, form);
      if (!data?.success || !data?.user) throw new Error(data?.msg || 'The backend did not confirm the request.');
      onLogin(data.user);
    } catch (err) {
      setError(getApiError(err, mode === 'login' ? 'Unable to sign in.' : 'Unable to create your account.'));
    } finally { setBusy(false); }
  };

  const useDemo = () => onLogin({ id: 'demo', name: 'Demo Traveler', phone: '', emergency_name: 'Trusted Contact', emergency_phone: '', demo: true });
  const changeMode = (next) => { setMode(next); setStep(1); setError(''); };

  return (
    <main className="auth-page">
      <section className="auth-story">
        <div className="auth-story-overlay" />
        <div className="auth-brand"><span className="brand-mark"><ShieldCheck size={24} /></span><span>Sakhi<span className="brand-accent">-Sahayak</span></span></div>
        <div className="auth-story-copy">
          <span className="eyebrow"><Radio size={14} /> PERSONAL SAFETY, BUILT AROUND YOU</span>
          <h1>Your journey.<br /><span>More confidence.</span></h1>
          <p>Safety insights, route planning, trusted contacts and a connected emergency workflow—together in one place.</p>
          <div className="auth-feature-list">
            <div><MapPinned size={18} /><span><b>Safety-aware routes</b><small>Explore risk layers and nearby support points.</small></span></div>
            <div><HeartHandshake size={18} /><span><b>Trusted support</b><small>Share location and reach your safety network.</small></span></div>
            <div><ShieldCheck size={18} /><span><b>Emergency assistance</b><small>Manual SOS and optional voice distress checks.</small></span></div>
          </div>
          <p className="auth-disclaimer">Safety information is decision support, not a guarantee of real-world safety.</p>
        </div>
      </section>

      <section className="auth-panel">
        <div className="auth-card">
          <div className="auth-card-heading"><span className="auth-icon"><ShieldCheck size={23} /></span><div><p className="eyebrow">WELCOME TO SAKHI-SAHAYAK</p><h2>{mode === 'login' ? 'Sign in to your space' : 'Create your account'}</h2><p className="muted">{mode === 'login' ? 'Pick up where your safety journey left off.' : 'Set up your profile and a trusted emergency contact.'}</p></div></div>
          <div className="auth-tabs" role="tablist" aria-label="Account access">
            <button type="button" role="tab" aria-selected={mode === 'login'} className={mode === 'login' ? 'selected' : ''} onClick={() => changeMode('login')}>Sign in</button>
            <button type="button" role="tab" aria-selected={mode === 'signup'} className={mode === 'signup' ? 'selected' : ''} onClick={() => changeMode('signup')}>Create account</button>
          </div>

          <form className="auth-form" onSubmit={mode === 'signup' && step === 1 ? (e) => { e.preventDefault(); setStep(2); setError(''); } : submit}>
            {mode === 'signup' && step === 1 && <div className="step-label">STEP 1 OF 2 <span>Personal details</span></div>}
            {mode === 'signup' && step === 1 && <label>Full name<input name="userName" value={form.userName} onChange={update} autoComplete="name" placeholder="Your full name" required minLength={2} /></label>}
            <label>Phone number<div className="input-with-icon"><Phone size={17} /><input name="userPhone" value={form.userPhone} onChange={update} autoComplete="tel" placeholder="+91 98765 43210" inputMode="tel" required /></div></label>
            <label>Password<div className="input-with-icon"><LockKeyhole size={17} /><input type="password" name="userPassword" value={form.userPassword} onChange={update} autoComplete={mode === 'login' ? 'current-password' : 'new-password'} placeholder="Enter your password" required minLength={mode === 'signup' ? 8 : undefined} /></div>{mode === 'signup' && <small className="field-hint">Use at least 8 characters.</small>}</label>
            {mode === 'signup' && step === 2 && <>
              <div className="step-label">STEP 2 OF 2 <span>Trusted emergency contact</span></div>
              <label>Contact name<input name="emergencyName" value={form.emergencyName} onChange={update} autoComplete="off" placeholder="Person you trust" required /></label>
              <label>Contact phone<input name="emergencyPhone" value={form.emergencyPhone} onChange={update} autoComplete="off" placeholder="Emergency contact number" inputMode="tel" required /></label>
            </>}
            {error && <div className="form-error" role="alert">{error}</div>}
            {mode === 'signup' && step === 2 ? <div className="form-actions"><button className="button button-ghost" type="button" onClick={() => setStep(1)}><ArrowLeft size={17} /> Back</button><button className="button button-primary" type="submit" disabled={busy}>{busy ? <LoaderCircle className="spin" size={18} /> : null}Create account</button></div> : <button className="button button-primary button-full" type="submit" disabled={busy}>{busy ? <LoaderCircle className="spin" size={18} /> : null}{mode === 'login' ? 'Sign in securely' : 'Continue'}<ArrowRight size={17} /></button>}
          </form>
          {mode === 'login' && <div className="demo-area"><div className="divider-label"><span /> <small>JUST EXPLORING?</small> <span /></div><button type="button" className="button button-ghost button-full" onClick={useDemo}><Users size={17} /> Open demo dashboard</button><p>Demo mode previews the interface; backend-dependent features still require the server.</p></div>}
          <p className="auth-privacy">Your location is requested by your browser and shared while using live tracking features.</p>
        </div>
        <footer className="auth-footer">© {new Date().getFullYear()} Sakhi-Sahayak <span>Built for safer journeys</span></footer>
      </section>
    </main>
  );
}
