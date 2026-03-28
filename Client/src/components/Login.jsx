import { useState } from 'react';
import { ShieldCheck } from 'lucide-react';
import axios from 'axios';

export default function Login({ onLogin }) {
  const [mode, setMode] = useState('login'); // 'login' or 'signup'
  const [step, setStep] = useState(1);
  const [errorMsg, setErrorMsg] = useState('');
  
  const [formData, setFormData] = useState({
    userName: '',
    userPhone: '',
    userPassword: '',
    emergencyName: '',
    emergencyPhone: ''
  });

  const handleChange = (e) => {
    setFormData({ ...formData, [e.target.name]: e.target.value });
  };

  const handleNext = (e) => {
    e.preventDefault();
    if (mode === 'signup') {
      if (formData.userName && formData.userPhone && formData.userPassword) {
        setStep(2);
      }
    }
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setErrorMsg('');
    try {
      if (mode === 'login') {
        const resp = await axios.post('http://localhost:5001/api/login', formData);
        if (resp.data.success) {
          onLogin(resp.data.user);
        } else {
          setErrorMsg(resp.data.msg || 'Login failed');
        }
      } else {
        const resp = await axios.post('http://localhost:5001/api/signup', formData);
        if (resp.data.success) {
          onLogin(resp.data.user);
        } else {
          setErrorMsg(resp.data.msg || 'Signup failed');
        }
      }
    } catch (err) {
      setErrorMsg(err.response?.data?.error || err.response?.data?.msg || 'An error occurred connecting to Backend. Check your MongoDB Atlas IP Whitelist settings.');
    }
  };

  return (
    <div className="login-page">
      <div className="auth-card glass" style={{ minHeight: '450px', display: 'flex', flexDirection: 'column', justifyContent: 'center' }}>
        <ShieldCheck size={80} color="#FF2E63" style={{ margin: '0 auto 20px' }} />
        <h1 className="gradient-text" style={{ fontSize: '2.5rem', marginBottom: '10px' }}>
          Sakhi-Sahayak
        </h1>
        <p style={{ color: '#94A3B8', marginBottom: '20px' }}>
          24/7 Safety & Live Location Tracking
        </p>

        <div style={{ display: 'flex', gap: '10px', marginBottom: '20px', justifyContent: 'center' }}>
          <button 
            type="button"
            className="btn" 
            style={{ padding: '0.5rem 1rem', background: mode === 'login' ? 'var(--primary)' : '#334155' }} 
            onClick={() => { setMode('login'); setStep(1); setErrorMsg(''); }}
          >
            Login
          </button>
          <button 
            type="button"
            className="btn" 
            style={{ padding: '0.5rem 1rem', background: mode === 'signup' ? 'var(--primary)' : '#334155' }} 
            onClick={() => { setMode('signup'); setStep(1); setErrorMsg(''); }}
          >
            Sign Up
          </button>
        </div>

        {errorMsg && (
          <div style={{ color: '#EF4444', background: 'rgba(239, 68, 68, 0.1)', padding: '10px', borderRadius: '8px', marginBottom: '15px' }}>
            {errorMsg}
          </div>
        )}

        {mode === 'login' && (
          <form onSubmit={handleSubmit} style={{ animation: 'slideUp 0.4s ease' }}>
            <div style={{ textAlign: 'left', marginBottom: '15px' }}>
              <label style={{ fontSize: '0.9rem', color: '#CBD5E1' }}>Registered Phone Number</label>
              <input type="text" name="userPhone" value={formData.userPhone} onChange={handleChange} placeholder="+91 98765 43210" required />
            </div>
            <div style={{ textAlign: 'left', marginBottom: '25px' }}>
              <label style={{ fontSize: '0.9rem', color: '#CBD5E1' }}>Password</label>
              <input type="password" name="userPassword" value={formData.userPassword} onChange={handleChange} placeholder="Enter Password" required />
            </div>

            <button type="submit" className="btn">
              Login to Dashboard
            </button>
          </form>
        )}

        {mode === 'signup' && step === 1 && (
          <form onSubmit={handleNext} style={{ animation: 'slideUp 0.4s ease' }}>
            <h3 style={{ color: 'white', marginBottom: '15px', fontSize: '1.1rem' }}>Step 1: Personal Details</h3>
            
            <div style={{ textAlign: 'left', marginBottom: '15px' }}>
              <label style={{ fontSize: '0.9rem', color: '#CBD5E1' }}>Your Full Name</label>
              <input type="text" name="userName" value={formData.userName} onChange={handleChange} placeholder="e.g. Priya Sharma" required />
            </div>
            <div style={{ textAlign: 'left', marginBottom: '15px' }}>
              <label style={{ fontSize: '0.9rem', color: '#CBD5E1' }}>Your Phone Number</label>
              <input type="text" name="userPhone" value={formData.userPhone} onChange={handleChange} placeholder="+91 98765 43210" required />
            </div>
            <div style={{ textAlign: 'left', marginBottom: '25px' }}>
              <label style={{ fontSize: '0.9rem', color: '#CBD5E1' }}>Create Password</label>
              <input type="password" name="userPassword" value={formData.userPassword} onChange={handleChange} placeholder="Enter Password" required />
            </div>

            <button type="submit" className="btn">
              Next &rarr;
            </button>
          </form>
        )}

        {mode === 'signup' && step === 2 && (
          <form onSubmit={handleSubmit} style={{ animation: 'slideUp 0.4s ease' }}>
            <h3 style={{ color: '#EF4444', marginBottom: '15px', fontSize: '1.1rem' }}>Step 2: Emergency Contacts</h3>
            <p style={{ color: '#94A3B8', fontSize: '0.8rem', paddingBottom: '15px' }}>We securely send your live GPS here in an emergency.</p>
            
            <div style={{ textAlign: 'left', marginBottom: '15px' }}>
              <label style={{ fontSize: '0.9rem', color: '#CBD5E1' }}>Emergency Contact Name</label>
              <input type="text" name="emergencyName" value={formData.emergencyName} onChange={handleChange} placeholder="e.g. Papa / Police" required />
            </div>
            <div style={{ textAlign: 'left', marginBottom: '25px' }}>
              <label style={{ fontSize: '0.9rem', color: '#CBD5E1' }}>Emergency Contact Number</label>
              <input type="text" name="emergencyPhone" value={formData.emergencyPhone} onChange={handleChange} placeholder="+91 99999 88888" required />
            </div>

            <div style={{ display: 'flex', gap: '10px' }}>
              <button type="button" className="btn" style={{ background: '#334155' }} onClick={() => setStep(1)}>
                &larr; Back
              </button>
              <button type="submit" className="btn">
                Complete Signup
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
