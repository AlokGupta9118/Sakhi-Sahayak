import './sarthi-mode.css';

import { createElement, useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { useNavigate } from 'react-router-dom';

import {

  Activity,

  AlertTriangle,

  ArrowRight,

  AudioLines,

  CheckCircle2,

  ChevronDown,

  CircleHelp,

  Clock3,

  Compass,

  HeartPulse,

  Hospital,

  LocateFixed,

  LogOut,

  Map as MapIcon,

  MapPin,

  Menu,

  Mic,

  Navigation,

  Phone,

  Radio,

  RefreshCw,

  Route,

  Shield,

  ShieldAlert,

  ShieldCheck,

  Siren,

  SlidersHorizontal,

  Users,

  X,

} from 'lucide-react';

import SarthiMap from './SarthiMap';

import { useTracker } from '../hooks/useTracker';

import { api, API_BASE_URL, getApiError } from '../lib/api';

import { socket } from '../lib/socket';



const DEFAULT_LAYERS = { dangerZones: true, blackSpots: true, policeStations: true, hospitals: true, metroStations: true, safeZones: true, tacticalUnits: true, hostels: false, education: false, corporate: false };

const asCount = (data, key) => Array.isArray(data?.[key]) ? data[key].length : 0;

const prettyStatus = (status = 'IDLE') => status.replaceAll('_', ' ').toLowerCase().replace(/^\w/, (c) => c.toUpperCase());



function MetricCard({ icon: Icon, label, value, detail, tone = 'indigo' }) {

  return <article className="metric-card"><div className={`metric-icon tone-${tone}`}>{createElement(Icon, { size: 20 })}</div><div className="metric-copy"><p>{label}</p><strong>{value ?? '—'}</strong><small>{detail}</small></div></article>;

}



function VoiceCheck({ user, location, connected, agentState, onAnalysis }) {

  const [recording, setRecording] = useState(false);

  const [busy, setBusy] = useState(false);

  const [message, setMessage] = useState('Voice checks are off until you start one.');

  const [transcript, setTranscript] = useState('');

  const recorderRef = useRef(null);

  const streamRef = useRef(null);

  const timerRef = useRef(null);

  const chunksRef = useRef([]);

  const unmountingRef = useRef(false);



  const cleanup = useCallback(() => {

    if (timerRef.current) window.clearTimeout(timerRef.current);

    timerRef.current = null;

    streamRef.current?.getTracks().forEach((track) => track.stop());

    streamRef.current = null;

  }, []);

  useEffect(() => () => { unmountingRef.current = true; try { recorderRef.current?.state !== 'inactive' && recorderRef.current?.stop(); } catch { /* Recorder may already be stopped during unmount. */ } cleanup(); }, [cleanup]);



  const upload = useCallback(async (blob) => {

    if (!blob || blob.size < 500) { setMessage('No clear audio captured. Please try again in a quieter place.'); return; }

    if (!connected || !socket.id) { setMessage('Safety server disconnected. Reconnect before sending a voice check.'); return; }

    setBusy(true); setMessage('Transcribing audio and checking the safety workflow…'); setTranscript('');

    try {

      const body = new FormData();

      body.append('audio', blob, 'voice-check.webm');

      body.append('socketId', socket.id);

      body.append('userName', user?.name || user?.userName || 'Traveler');

      body.append('userPhone', user?.phone || user?.userPhone || '');

      body.append('lat', String(location.lat)); body.append('lng', String(location.lng));

      const { data } = await api.post('/api/transcribe', body, { timeout: 180000 });

      const text = data.transcript || '';

      setTranscript(text);

      setMessage(text ? (data.analysis?.summary || `Transcription complete${data.distress_detected ? ' — distress workflow flagged this clip' : ''}.`) : 'No speech was recognized in this clip.');

      if (data.distress_detected && data.analysis?.trackingId && socket.connected) {

        const dataUrl = await new Promise((resolve, reject) => { const reader = new FileReader(); reader.onload = () => resolve(reader.result); reader.onerror = reject; reader.readAsDataURL(blob); });

        socket.emit('evidence-upload', { trackingId: data.analysis.trackingId, audioData: String(dataUrl).split(',')[1], format: 'webm' });

        setMessage('Distress workflow flagged this clip. The clip was forwarded to the active incident as evidence.');

      }

      onAnalysis?.({ ...data, receivedAt: new Date().toISOString() });

    } catch (error) { setMessage(getApiError(error, 'Voice analysis failed. Check Whisper and FFmpeg on the backend.')); }

    finally { setBusy(false); cleanup(); }

  }, [connected, user, location, onAnalysis, cleanup]);



  const start = async () => {

    if (!connected) { setMessage('Connect to the safety server before recording.'); return; }

    if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) { setMessage('This browser does not support microphone recording.'); return; }

    try {

      const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true }, video: false });

      streamRef.current = stream; chunksRef.current = [];

      const preferred = ['audio/webm;codecs=opus', 'audio/webm'].find((type) => window.MediaRecorder.isTypeSupported?.(type));

      const recorder = preferred ? new MediaRecorder(stream, { mimeType: preferred }) : new MediaRecorder(stream);

      recorderRef.current = recorder;

      recorder.ondataavailable = (event) => { if (event.data?.size) chunksRef.current.push(event.data); };

      unmountingRef.current = false;

      recorder.onstop = () => {

        const blob = new Blob(chunksRef.current, { type: recorder.mimeType || 'audio/webm' });

        setRecording(false); cleanup();

        if (!unmountingRef.current) void upload(blob);

      };

      recorder.start(); setRecording(true); setMessage('Listening for up to 7 seconds. Speak naturally in a language supported by the backend.');

      timerRef.current = window.setTimeout(() => { if (recorder.state !== 'inactive') recorder.stop(); }, 7000);

    } catch (error) { cleanup(); setMessage(error?.name === 'NotAllowedError' ? 'Microphone permission was denied. Enable it in your browser settings to use voice checks.' : 'Could not open the microphone. Check that another app is not using it.'); }

  };

  const stop = () => { if (recorderRef.current?.state === 'recording') recorderRef.current.stop(); };



  return <section className="panel voice-panel"><div className="panel-heading"><div className="heading-icon tone-violet"><AudioLines size={19} /></div><div><h3>Voice safety check</h3><p>Short, user-started recording · routed to the voice agent</p></div><span className={`status-pill ${recording ? 'status-live' : ''}`}><span />{recording ? 'Listening' : busy ? 'Analysing' : 'On demand'}</span></div>

    <p className="voice-message">{message}</p>{transcript && <blockquote className="transcript"><small>TRANSCRIPT</small>{transcript}</blockquote>}

    <div className="voice-actions"><button className={`button ${recording ? 'button-danger' : 'button-primary'}`} onClick={recording ? stop : start} disabled={busy || (!recording && !connected)}>{busy ? <RefreshCw size={17} className="spin" /> : recording ? <span className="record-dot" /> : <Mic size={17} />}{recording ? 'Stop and analyse' : busy ? 'Analysing audio…' : 'Start 7-second check'}</button><small>Audio is sent for transcription. If a distress event is flagged, the clip may be saved with that incident.</small></div>

    {agentState?.status && agentState.status !== 'IDLE' && <div className="agent-state-line"><Activity size={15} /> Voice agent: <b>{prettyStatus(agentState.status)}</b>{agentState.trackingId ? <span>· {agentState.trackingId}</span> : null}</div>}

  </section>;

}



function EvidencePanel({ initialTrackingId }) {

  const [trackingId, setTrackingId] = useState(initialTrackingId || '');

  const [file, setFile] = useState(null);

  const [files, setFiles] = useState([]);

  const [busy, setBusy] = useState(false);

  const [error, setError] = useState('');

  const [message, setMessage] = useState('');

  useEffect(() => { if (initialTrackingId) setTrackingId(initialTrackingId); }, [initialTrackingId]);

  const listFiles = async (requestedId = trackingId) => {

    const id = requestedId.trim();

    if (!id) { setError('Enter an incident tracking ID first.'); return; }

    setBusy(true); setError('');

    try { const { data } = await api.get(`/api/evidence/${encodeURIComponent(id)}`); setFiles(data.files || []); }

    catch (err) { setError(getApiError(err, 'Could not load incident evidence.')); }

    finally { setBusy(false); }

  };

  const upload = async (event) => {

    event.preventDefault(); if (!file) { setError('Choose a file to upload.'); return; }

    setBusy(true); setError(''); setMessage('');

    try {

      const form = new FormData(); form.append('evidence', file); form.append('trackingId', trackingId.trim() || 'UNKNOWN');

      const { data } = await api.post('/api/upload-evidence', form, { timeout: 180000 });

      setMessage(`Evidence uploaded: ${data.filename}`); setFile(null);

      if (data.trackingId) setTrackingId(data.trackingId);

      await listFiles(data.trackingId || trackingId);

    } catch (err) { setError(getApiError(err, 'Evidence upload failed.')); }

    finally { setBusy(false); }

  };

  return <section className="panel evidence-panel"><div className="panel-heading"><div className="heading-icon tone-violet"><ShieldCheck size={19} /></div><div><h3>Incident evidence</h3><p>Upload a file or view evidence linked to a tracking ID.</p></div></div><form className="evidence-form" onSubmit={upload}><label>Tracking ID<input value={trackingId} onChange={(e) => setTrackingId(e.target.value)} placeholder="Enter incident ID" /></label><label>Evidence file<input type="file" accept="audio/*,video/*,image/*,.pdf" onChange={(e) => setFile(e.target.files?.[0] || null)} /></label>{file && <p className="evidence-file-name">{file.name} · {(file.size / (1024 * 1024)).toFixed(2)} MB</p>}<div className="evidence-actions"><button className="button button-primary" type="submit" disabled={busy || !file}>{busy ? <RefreshCw size={15} className="spin" /> : <ShieldCheck size={15} />}Upload evidence</button><button className="button button-ghost" type="button" onClick={listFiles} disabled={busy || !trackingId.trim()}>View files</button></div></form>{error && <p className="evidence-error">{error}</p>}{message && <p className="evidence-success">{message}</p>}{files.length > 0 && <div className="evidence-file-list"><b>Saved files</b>{files.map((name) => <a key={name} href={`${API_BASE_URL}/evidence/${encodeURIComponent(name)}`} target="_blank" rel="noreferrer">{name}<ArrowRight size={13} /></a>)}</div>}{!files.length && !message && <p className="helper-text">Only upload evidence you are authorized to share. Backend upload limit: 50 MB.</p>}</section>;

}



export default function Dashboard({ user = {}, onLogout }) {

  const navigate = useNavigate();

  const tracker = useTracker(user);

  const { location, locationStatus, socketConnected, isSarthiActive, toggleSarthiMode, toggleSarthiMic, sarthiMicStatus, isSarthiAlarm, cancelSarthiAlarm, isSOS, triggerSOS, agentState, voiceAnalysis, setVoiceAnalysis, confirmSafe, cancelIntercept } = tracker;

  const [tab, setTab] = useState('home');

  const [mobileMenu, setMobileMenu] = useState(false);
  const [checkInSeconds, setCheckInSeconds] = useState(15);
  const [checkInHandled, setCheckInHandled] = useState(false);

  const [safetyData, setSafetyData] = useState(null);

  const [metrics, setMetrics] = useState(null);

  const [nearest, setNearest] = useState(null);

  const [nearestStation, setNearestStation] = useState(null);

  const [dataLoading, setDataLoading] = useState(true);

  const [dataError, setDataError] = useState('');

  const [refreshing, setRefreshing] = useState(false);

  const [layers, setLayers] = useState(DEFAULT_LAYERS);

  const [showLayers, setShowLayers] = useState(false);

  const [startText, setStartText] = useState('');

  const [endText, setEndText] = useState('');

  const [optimization, setOptimization] = useState('safest');

  const [routePicker, setRoutePicker] = useState(null);

  const [routeStart, setRouteStart] = useState(null);

  const [routeEnd, setRouteEnd] = useState(null);

  const [routeResult, setRouteResult] = useState(null);

  const [routeBusy, setRouteBusy] = useState(false);

  const [routeError, setRouteError] = useState('');

  const [routeHealth, setRouteHealth] = useState(null);

  const [notice, setNotice] = useState('');



  const loadSafetyData = useCallback(async (quiet = false) => {

    if (!quiet) setDataLoading(true);

    setDataError('');

    try {

      const [dataResponse, metricsResponse, healthResponse, zonesResponse, stationsResponse] = await Promise.all([

        api.get('/api/safety-data'), api.get('/api/safety-metrics'), api.get('/api/safe-route/health').catch(() => ({ data: null })),

        api.get('/api/danger-zones').catch(() => ({ data: null })), api.get('/api/police-stations').catch(() => ({ data: null })),

      ]);

      const combined = { ...(dataResponse.data || {}) };

      if (Array.isArray(zonesResponse.data)) combined.danger_zones = zonesResponse.data;

      if (Array.isArray(stationsResponse.data?.stations) && stationsResponse.data.stations.length) combined.police_stations = stationsResponse.data.stations;

      setSafetyData(combined); setMetrics(metricsResponse.data || {}); setRouteHealth(healthResponse.data);

    } catch (error) { setDataError(getApiError(error, 'Could not load safety data.')); }

    finally { setDataLoading(false); setRefreshing(false); }

  }, []);



  useEffect(() => { void loadSafetyData(); }, [loadSafetyData]);

  const nearestLat = Math.round((location?.lat || 0) * 1000) / 1000;

  const nearestLng = Math.round((location?.lng || 0) * 1000) / 1000;

  useEffect(() => {

    if (!Number.isFinite(nearestLat) || !Number.isFinite(nearestLng)) return;

    let cancelled = false;

    const timer = window.setTimeout(async () => {

      try {

        const [nearby, station] = await Promise.all([

          api.get('/api/nearest', { params: { lat: nearestLat, lng: nearestLng } }),

          api.get('/api/sos-nearest-station', { params: { lat: nearestLat, lng: nearestLng } }).catch(() => ({ data: null })),

        ]);

        if (!cancelled) { setNearest(nearby.data); setNearestStation(station.data?.station || null); }

      } catch { /* nearest services are optional; map and route planner remain available */ }

    }, 900);

    return () => { cancelled = true; window.clearTimeout(timer); };

  }, [nearestLat, nearestLng]);



  useEffect(() => {

    const onEmergency = (payload) => setNotice(`Emergency workflow update${payload?.trackingId ? ` · ${payload.trackingId}` : ''}`);

    const onEvidence = (payload) => setNotice(`Evidence saved${payload?.trackingId ? ` · ${payload.trackingId}` : ''}`);

    socket.on('emergency-broadcast-sent', onEmergency); socket.on('evidence-saved', onEvidence);

    return () => { socket.off('emergency-broadcast-sent', onEmergency); socket.off('evidence-saved', onEvidence); };

  }, []);



  const routeOptions = useMemo(() => {

    if (!routeResult?.route?.length) return [];

    return [{ id: 'recommended', label: `${optimization[0].toUpperCase()}${optimization.slice(1)} route`, coords: routeResult.route, color: optimization === 'shortest' ? '#2563eb' : optimization === 'balanced' ? '#7c3aed' : '#059669', distanceKm: routeResult.route_stats?.total_distance_km, score: routeResult.route_stats?.model_based_safety_score }];

  }, [routeResult, optimization]);



  const resolveCoords = async (value) => {

    const input = value.trim();

    const match = input.match(/^\s*(-?\d+(?:\.\d+)?)\s*[, ]\s*(-?\d+(?:\.\d+)?)\s*$/);

    if (match) {

      const lat = Number(match[1]);
      const lng = Number(match[2]);

      if (!Number.isFinite(lat) || !Number.isFinite(lng) ||
          Math.abs(lat) > 90 || Math.abs(lng) > 180) {
        throw new Error('Coordinates are outside the valid latitude/longitude range. Use latitude, longitude.');
      }

      return { lat, lng };

    }

    if (!input) throw new Error('Enter a place name or coordinates.');

    const response = await fetch(`https://nominatim.openstreetmap.org/search?format=jsonv2&limit=1&countrycodes=in&q=${encodeURIComponent(`${input}, Nagpur, Maharashtra, India`)}`, { headers: { Accept: 'application/json' } });

    if (!response.ok) throw new Error('Place search is temporarily unavailable. You can enter coordinates instead.');

    const results = await response.json();

    if (!results.length) throw new Error(`Could not find “${input}”. Try a landmark or coordinates (latitude, longitude).`);

    return { lat: Number(results[0].lat), lng: Number(results[0].lon) };

  };



  const calculateRoute = async (event) => {

    event?.preventDefault(); setRouteError(''); setRouteBusy(true); setRouteResult(null);

    try {

      const startInput = startText.trim() ||
        (locationStatus === 'live' && !location?.isApproximate
          ? `${location.lat}, ${location.lng}`
          : '');
      if (!startInput) {
        throw new Error('Live GPS is not available. Enter starting coordinates (latitude, longitude) or enable browser location access.');
      }

      const start = await resolveCoords(startInput);
      const end = await resolveCoords(endText);

      const { data } = await api.post('/api/safe-route', { start, end, optimization, compareModes: true }, { timeout: 180000 });

      if (!data.success || !data.found || !Array.isArray(data.route) || data.route.length < 2) throw new Error(data.error || 'The planner could not find a route for these coordinates.');

      setRouteStart(start); setRouteEnd(end); setRouteResult(data); setRoutePicker(null);

    } catch (error) { setRouteError(getApiError(error, 'Route planning failed.')); }

    finally { setRouteBusy(false); }

  };



  const chooseCurrentLocation = () => {
    if (locationStatus !== 'live' || location?.isApproximate) {
      setNotice('Live GPS is not available yet. Allow location permission, or enter starting coordinates manually.');
      return;
    }
    setStartText(`${location.lat.toFixed(6)}, ${location.lng.toFixed(6)}`);
    setRouteStart({ lat: location.lat, lng: location.lng });
    setRoutePicker(null);
    setNotice('Live GPS selected as the route starting point.');
  };

  const onMapClick = (point) => {

    if (routePicker === 'start') { setStartText(`${point.lat.toFixed(6)}, ${point.lng.toFixed(6)}`); setRouteStart(point); setRoutePicker('end'); }

    else if (routePicker === 'end') { setEndText(`${point.lat.toFixed(6)}, ${point.lng.toFixed(6)}`); setRouteEnd(point); setRoutePicker(null); }

  };

  const setActiveTab = (next) => { setTab(next); setMobileMenu(false); };

  useEffect(() => {
    if (!isSarthiAlarm) { setCheckInSeconds(15); setCheckInHandled(false); return; }
    setCheckInSeconds(15);
    setCheckInHandled(false);
  }, [isSarthiAlarm]);

  useEffect(() => {
    if (!isSarthiAlarm || checkInSeconds <= 0) return;
    const timer = window.setTimeout(() => setCheckInSeconds((seconds) => Math.max(0, seconds - 1)), 1000);
    return () => window.clearTimeout(timer);
  }, [isSarthiAlarm, checkInSeconds]);

  useEffect(() => {
    if (!isSarthiAlarm || checkInSeconds !== 0 || checkInHandled) return;
    setCheckInHandled(true);
    cancelSarthiAlarm();
    triggerSOS({ skipConfirm: true });
  }, [isSarthiAlarm, checkInSeconds, checkInHandled, cancelSarthiAlarm, triggerSOS]);

  const handleSarthi = () => {

    if (!isSarthiActive && (locationStatus !== 'live' || location.isApproximate)) { setNotice('Allow browser location access first so Sarthi can check movement accurately.'); return; }

    toggleSarthiMode(); setNotice(isSarthiActive ? 'Sarthi monitoring paused.' : 'Sarthi activated. Allow microphone access to enable live audio checks; a no-movement check appears after 15 seconds.');

  };

  const handleRefresh = () => { setRefreshing(true); void loadSafetyData(true); };

  const userName = user?.name || user?.userName || 'Traveler';

  const blackSpotCount = asCount(safetyData, 'black_spots');

  const stationCount = asCount(safetyData, 'police_stations');

  const clusterCount = metrics?.danger_zone_clusters ?? asCount(safetyData, 'danger_zones');

  const supportCount = stationCount + asCount(safetyData, 'hospitals');

  const routeComparison = routeResult?.route_comparison || {};



  const navItems = [

    { id: 'home', label: 'Overview', icon: Activity }, { id: 'map', label: 'Safety map', icon: MapIcon },

    { id: 'emergency', label: 'Emergency support', icon: ShieldAlert }, { id: 'profile', label: 'My profile', icon: Users },

  ];



  return <div className="app-shell">

    <aside className={`app-sidebar ${mobileMenu ? 'sidebar-open' : ''}`}>

      <button className="brand-lockup" onClick={() => setActiveTab('home')}><span className="brand-mark"><ShieldCheck size={22} /></span><span>Sakhi<span className="brand-accent">-Sahayak</span><small>PERSONAL SAFETY SPACE</small></span></button>

      <div className="sidebar-section-label">YOUR SPACE</div>

      <nav className="sidebar-links" aria-label="Main navigation">{navItems.map(({ id, label, icon: Icon }) => <button key={id} className={`sidebar-link ${tab === id ? 'active' : ''}`} onClick={() => setActiveTab(id)}>{createElement(Icon, { size: 19 })}<span>{label}</span>{tab === id && <span className="nav-active-dot" />}</button>)}<button className="sidebar-link" onClick={() => navigate('/analytics')}><Activity size={19} /><span>Data insights</span></button><button className="sidebar-link" onClick={() => navigate('/community')}><Users size={19} /><span>Safety network</span></button><button className="sidebar-link" onClick={() => navigate('/family')}><HeartPulse size={19} /><span>Family live view</span></button></nav>

      <div className="sidebar-help-card"><div className="help-card-icon"><HeartPulse size={19} /></div><b>Need help right now?</b><p>Use SOS to start the connected emergency workflow.</p><a href="tel:112"><Phone size={15} /> Call India emergency helpline · 112</a></div>

      <div className="sidebar-user"><div className="avatar">{userName.trim().slice(0, 1).toUpperCase()}</div><div className="sidebar-user-copy"><b>{userName}</b><small>{user?.demo ? 'Demo session' : user?.phone || 'Signed in'}</small></div><button title="Sign out" aria-label="Sign out" className="icon-button" onClick={onLogout}><LogOut size={17} /></button></div>

    </aside>

    {mobileMenu && <button className="mobile-backdrop" aria-label="Close navigation" onClick={() => setMobileMenu(false)} />}



    <main className="main-area">

      <header className="topbar"><div className="topbar-left"><button className="icon-button mobile-menu-button" aria-label="Open menu" onClick={() => setMobileMenu(true)}><Menu size={20} /></button><div className="breadcrumb">Sakhi-Sahayak <span>/</span> <b>{navItems.find((item) => item.id === tab)?.label || 'Overview'}</b></div></div><div className="topbar-actions"><span className={`connection-chip ${socketConnected ? 'connected' : 'disconnected'}`}><span />{socketConnected ? 'Connected' : 'Reconnecting'}</span><button className="icon-button" title="Refresh safety data" onClick={handleRefresh} disabled={refreshing}><RefreshCw size={17} className={refreshing ? 'spin' : ''} /></button><button className="avatar avatar-small" title={userName} onClick={() => setActiveTab('profile')}>{userName.trim().slice(0, 1).toUpperCase()}</button></div></header>

      {notice && <div className="inline-notice"><CheckCircle2 size={16} />{notice}<button onClick={() => setNotice('')} aria-label="Dismiss notice"><X size={15} /></button></div>}

      {dataError && <div className="inline-error"><AlertTriangle size={17} /><span>{dataError}</span><button className="button button-ghost button-sm" onClick={handleRefresh}>Retry</button></div>}



      {tab === 'home' && <div className="page-content animate-fade">

        <section className="welcome-row"><div><span className="eyebrow"><span className="eyebrow-dot" /> YOUR PERSONAL SAFETY DASHBOARD</span><h1>Good to see you, <span>{userName.split(' ')[0]}.</span></h1><p>Stay aware of your surroundings, know your support options, and plan with better information.</p></div><div className="welcome-date"><Clock3 size={16} /><span>{new Intl.DateTimeFormat('en-IN', { weekday: 'short', day: 'numeric', month: 'short' }).format(new Date())}</span></div></section>

        <section className={`status-banner ${isSarthiActive ? 'sarthi-active-banner' : ''}`}><div className="status-banner-icon"><ShieldCheck size={23} /></div><div className="status-banner-copy"><b>{isSOS ? 'Emergency workflow active' : isSarthiActive ? 'Sarthi movement reminders are on' : 'You are in control of your safety tools'}</b><p>{isSOS ? `Current agent state: ${prettyStatus(agentState.status)}. If you need immediate help, call 112.` : isSarthiActive ? `Sarthi is active · movement check: 15 seconds · microphone: ${sarthiMicStatus === 'listening' ? 'listening' : sarthiMicStatus === 'blocked' ? 'permission needed' : sarthiMicStatus === 'error' ? 'unavailable' : 'starting'}.` : 'Location and microphone features run only with browser permission and your action.'}</p></div><div className="status-banner-actions"><button className={`button ${isSarthiActive ? 'button-secondary sarthi-glow-button' : 'button-ghost'}`} onClick={handleSarthi} disabled={!isSarthiActive && locationStatus !== 'live'}><Activity size={16} />{isSarthiActive ? 'Pause Sarthi' : 'Enable Sarthi'}</button><button className={sarthiMicStatus === 'listening' ? 'button button-secondary sarthi-glow-button' : 'button button-ghost'} onClick={() => void toggleSarthiMic()} disabled={!isSarthiActive}>{sarthiMicStatus === 'listening' ? 'Turn Voice Guard off' : 'Enable Voice Guard'}</button>{['THREAT_DETECTED', 'INTERCEPT_COUNTDOWN'].includes(agentState?.status) && <button className="button button-ghost" onClick={cancelIntercept}><CheckCircle2 size={16} /> I'm safe</button>}<button className="button button-danger" onClick={triggerSOS}><Siren size={17} /> SOS</button></div></section>

        <section className="metrics-grid">

          <MetricCard icon={AlertTriangle} label="Risk clusters" value={dataLoading ? '…' : clusterCount} detail="DBSCAN-derived map clusters" tone="rose" />

          <MetricCard icon={MapPin} label="Black spots" value={dataLoading ? '…' : blackSpotCount} detail="Points in the supplied dataset" tone="violet" />

          <MetricCard icon={Shield} label="Police stations" value={dataLoading ? '…' : stationCount} detail="Mapped support locations" tone="blue" />

          <MetricCard icon={Hospital} label="Support locations" value={dataLoading ? '…' : supportCount} detail="Police stations + hospitals" tone="green" />

        </section>

        <div className="home-grid">

          <section className="panel map-preview-panel"><div className="panel-heading"><div><span className="eyebrow">GEOSPATIAL INTELLIGENCE</span><h2>Safety map</h2><p>Explore the supplied risk clusters and nearby support points.</p></div><button className="button button-ghost button-sm" onClick={() => setActiveTab('map')}>Open map <ArrowRight size={15} /></button></div><div className="preview-map"><SarthiMap location={location} safetyData={safetyData} dangerZones={safetyData?.danger_zones || []} layers={{ ...DEFAULT_LAYERS, hostels: false, education: false, corporate: false }} isSOS={isSOS} isSarthiActive={isSarthiActive} /></div><div className="map-legend"><span><i className="legend-dot danger" /> Risk cluster</span><span><i className="legend-dot police" /> Police</span><span><i className="legend-dot hospital" /> Hospital</span><span><i className="legend-dot blackspot" /> Black spot</span></div></section>

          <div className="home-side-stack">

            <section className="panel location-panel"><div className="panel-heading"><div className="heading-icon tone-blue"><LocateFixed size={19} /></div><div><h3>Your location</h3><p>{locationStatus === 'live' ? 'Browser GPS location' : locationStatus === 'denied' ? 'Location permission denied' : locationStatus === 'unsupported' ? 'GPS not supported' : 'Waiting for location'}</p></div><span className={`mini-status ${locationStatus === 'live' ? 'ok' : 'warn'}`}><span /></span></div><div className="coordinates"><span>{location.lat.toFixed(5)}</span><span>{location.lng.toFixed(5)}</span></div>{location.isApproximate && <p className="helper-text">Showing approximate Nagpur center until GPS permission is available.</p>}<button className="button button-ghost button-full" onClick={() => { chooseCurrentLocation(); setActiveTab('map'); }}>Plan from here <Navigation size={16} /></button></section>

            <section className="panel support-panel"><div className="panel-heading"><div className="heading-icon tone-green"><HeartPulse size={19} /></div><div><h3>Nearest support</h3><p>Based on your current coordinates</p></div></div>{nearest?.police_station ? <div className="nearby-row"><span className="nearby-icon blue"><Shield size={17} /></span><div><b>{nearest.police_station.name || 'Police station'}</b><small>{nearest.police_station.distanceText || 'Distance unavailable'}</small></div></div> : <div className="empty-state compact"><p>Nearest police station is not available yet.</p></div>}{nearest?.hospital ? <div className="nearby-row"><span className="nearby-icon red"><Hospital size={17} /></span><div><b>{nearest.hospital.name || 'Hospital'}</b><small>{nearest.hospital.distanceText || 'Distance unavailable'}</small></div></div> : null}<a className="text-link" href="tel:112"><Phone size={15} /> Emergency help · 112</a></section>

          </div>

        </div>

        <div className="section-heading"><div><h2>Quick actions</h2><p>Useful tools for your next journey.</p></div></div>

        <section className="quick-actions-grid"><button className="quick-action" onClick={() => setActiveTab('map')}><span className="quick-action-icon tone-green"><Route size={21} /></span><b>Plan a safer route</b><p>Compare shortest, balanced and safety-weighted paths.</p><ArrowRight size={17} className="quick-arrow" /></button><button className="quick-action" onClick={handleSarthi} disabled={!isSarthiActive && locationStatus !== 'live'}><span className="quick-action-icon tone-violet"><Activity size={21} /></span><b>{isSarthiActive ? 'Pause Sarthi' : 'Enable Sarthi'}</b><p>Turn on an inactivity reminder while you travel.</p><ArrowRight size={17} className="quick-arrow" /></button><button className="quick-action" onClick={() => setActiveTab('emergency')}><span className="quick-action-icon tone-rose"><HeartPulse size={21} /></span><b>Trusted contact & help</b><p>Review your emergency contact and nearby services.</p><ArrowRight size={17} className="quick-arrow" /></button><button className="quick-action" onClick={() => navigate('/analytics')}><span className="quick-action-icon tone-blue"><Activity size={21} /></span><b>Dataset insights</b><p>Review source coverage and geospatial data counts.</p><ArrowRight size={17} className="quick-arrow" /></button></section>

        <VoiceCheck user={user} location={location} connected={socketConnected} agentState={agentState} onAnalysis={setVoiceAnalysis} />

        {voiceAnalysis?.transcript && <div className={`analysis-summary ${voiceAnalysis.distress_detected ? 'analysis-alert' : ''}`}><div className="analysis-icon"><AudioLines size={18} /></div><div><b>{voiceAnalysis.distress_detected ? 'Voice agent flagged this clip' : 'Latest voice check'}</b><p>{voiceAnalysis.analysis?.summary || `Language: ${voiceAnalysis.language || 'unknown'}`}</p></div></div>}

        <p className="safety-footnote"><CircleHelp size={15} /> Risk clusters and route scores are based on the supplied dataset and model heuristics; they are not guarantees of safety or validated crime probabilities.</p>

      </div>}



      {tab === 'map' && <div className="map-page animate-fade"><div className="map-page-heading"><div><span className="eyebrow">EXPLORE YOUR AREA</span><h1>Safety map & routes</h1><p>Tap the map to set route endpoints or enter a place name / latitude, longitude.</p></div><div className="map-page-actions"><span className={`connection-chip ${routeHealth?.ready ? 'connected' : 'disconnected'}`}><span />{routeHealth?.ready ? 'Route engine ready' : 'Route engine checking'}</span><button className="button button-ghost" onClick={() => setShowLayers((value) => !value)}><SlidersHorizontal size={17} /> Layers <ChevronDown size={15} /></button></div></div>

        <div className="map-workspace"><aside className="route-sidebar"><div className="route-sidebar-heading"><div className="heading-icon tone-green"><Compass size={20} /></div><div><h2>Route planner</h2><p>Choose how you want to travel.</p></div></div><form className="route-form" onSubmit={calculateRoute}><label>Starting point<div className="route-input-wrap"><span className="route-point start-point">A</span><input value={startText} onChange={(e) => setStartText(e.target.value)} placeholder="Current location or place" /></div></label><button type="button" className="text-link current-location-link" onClick={chooseCurrentLocation}><LocateFixed size={15} /> Use my current location</button><label>Destination<div className="route-input-wrap"><span className="route-point end-point">B</span><input value={endText} onChange={(e) => setEndText(e.target.value)} placeholder="Enter destination" required /></div></label><div className="map-pick-actions"><button type="button" className={`button button-ghost button-sm ${routePicker === 'start' ? 'button-selected' : ''}`} onClick={() => setRoutePicker(routePicker === 'start' ? null : 'start')}>Pick start on map</button><button type="button" className={`button button-ghost button-sm ${routePicker === 'end' ? 'button-selected' : ''}`} onClick={() => setRoutePicker(routePicker === 'end' ? null : 'end')}>Pick end on map</button></div>{routePicker && <p className="pick-instruction"><MapPin size={15} /> Click anywhere on the map to set the {routePicker === 'start' ? 'starting point' : 'destination'}.</p>}

          <label>Route preference<select value={optimization} onChange={(e) => { setOptimization(e.target.value); setRouteResult(null); setRouteError(''); }}><option value="safest">Safety-weighted</option><option value="balanced">Balanced distance & risk</option><option value="shortest">Shortest distance</option></select></label><button className="button button-primary button-full route-submit" type="submit" disabled={routeBusy || !endText.trim()}>{routeBusy ? <RefreshCw size={17} className="spin" /> : <Route size={17} />}{routeBusy ? 'Calculating route…' : 'Find route'}<ArrowRight size={16} /></button><p className="route-time-note">The first request may take longer while the road graph is downloaded and cached.</p></form>

          {routeError && <div className="route-error"><AlertTriangle size={17} /><div><b>Could not calculate route</b><p>{routeError}</p>{routeHealth?.missing_dependencies?.length ? <small>Missing backend packages: {routeHealth.missing_dependencies.join(', ')}</small> : null}</div></div>}

          {routeResult && <div className="route-result"><div className="route-result-title"><span className="result-check"><CheckCircle2 size={17} /></span><div><b>{optimization === 'safest' ? 'Safety-weighted route' : optimization === 'balanced' ? 'Balanced route' : 'Shortest route'}</b><small>Route found by the backend planner</small></div></div><div className="route-result-stats"><div><small>Distance</small><b>{routeResult.route_stats?.total_distance_km?.toFixed?.(2) ?? '—'} km</b></div><div><small>Model score</small><b>{routeResult.route_stats?.model_based_safety_score ?? '—'}<span>/100</span></b></div></div><p className="score-caveat">Heuristic score from supplied risk data, not a validated probability or safety guarantee.</p><button className="button button-ghost button-full" onClick={() => { setRouteResult(null); setRouteError(''); }}>Clear route</button></div>}

          {showLayers && <div className="layer-controls"><div className="layer-controls-title"><b>Map layers</b><button className="icon-button" onClick={() => setShowLayers(false)} aria-label="Close layers"><X size={15} /></button></div>{Object.entries({ dangerZones: 'Risk clusters', blackSpots: 'Black spots', policeStations: 'Police stations', hospitals: 'Hospitals', metroStations: 'Metro stations', safeZones: 'Safe zones', tacticalUnits: 'Support units', hostels: 'Hostels / PGs', education: 'Educational institutions', corporate: 'Corporate areas' }).map(([key, label]) => <label className="layer-toggle" key={key}><span>{label}</span><input type="checkbox" checked={Boolean(layers[key])} onChange={(e) => setLayers((old) => ({ ...old, [key]: e.target.checked }))} /></label>)}</div>}

        </aside><div className="route-map-panel"><div className="map-floating-label"><span className="map-live-dot" />{routePicker ? `Select ${routePicker === 'start' ? 'start' : 'destination'} point` : routeResult ? 'Route preview' : 'Live safety layers'}<span className="map-label-divider" />{dataLoading ? 'Loading map data…' : `${metrics?.source_records ?? '—'} source records`}</div><SarthiMap location={location} safetyData={safetyData} dangerZones={safetyData?.danger_zones || []} isSOS={isSOS} isSarthiActive={isSarthiActive} routeOptions={routeOptions} routeStart={routeStart} routeEnd={routeEnd} layers={layers} onMapClick={onMapClick} /><div className="map-bottom-hint"><MapPin size={15} /> {routePicker ? 'Click the map to set this point.' : 'Map markers show locations from the supplied safety dataset.'}</div></div></div>

        {routeResult?.route_comparison && <section className="panel comparison-panel"><div className="panel-heading"><div><h3>Route trade-offs</h3><p>Calculated for the same origin and destination by the backend planner.</p></div></div><div className="comparison-grid">{['safest', 'balanced', 'shortest'].filter((key) => routeComparison[key]).map((key) => <div className={`comparison-card ${key === optimization ? 'comparison-selected' : ''}`} key={key}><span>{key === 'safest' ? 'Safety-weighted' : key === 'balanced' ? 'Balanced' : 'Shortest'}</span><b>{routeComparison[key].distance_km?.toFixed?.(2) ?? '—'} km</b><small>Model score: {routeComparison[key].model_based_safety_score ?? '—'}/100</small><small>Average risk index: {routeComparison[key].average_risk_score ?? '—'}</small></div>)}</div>{routeComparison.safest_vs_shortest && <p className="comparison-note">Safety-weighted vs shortest: distance change {routeComparison.safest_vs_shortest.distance_increase_percent ?? '—'}%; estimated risk-index reduction {routeComparison.safest_vs_shortest.risk_reduction_percent ?? '—'}%.</p>}</section>}

        <p className="safety-footnote"><CircleHelp size={15} /> Use route suggestions as decision support. Check current conditions and local guidance, and contact emergency services directly if needed.</p>

      </div>}



      {tab === 'emergency' && <div className="page-content narrow-page animate-fade"><section className="welcome-row"><div><span className="eyebrow">YOUR SUPPORT NETWORK</span><h1>Emergency support</h1><p>Review the contact registered with your account and find mapped support nearby.</p></div></section><section className="emergency-callout"><div className="emergency-callout-icon"><Siren size={27} /></div><div><h2>In immediate danger?</h2><p>Call India's emergency response number directly. Do not rely on the app alone.</p></div><a className="button button-danger" href="tel:112"><Phone size={17} /> Call 112</a></section><div className="support-detail-grid"><section className="panel"><div className="panel-heading"><div className="heading-icon tone-violet"><Users size={19} /></div><div><h3>Trusted emergency contact</h3><p>Information provided during account creation</p></div></div>{user?.emergency_name || user?.emergency_phone ? <div className="contact-card"><div className="avatar avatar-contact">{(user.emergency_name || 'T').slice(0, 1).toUpperCase()}</div><div><b>{user.emergency_name || 'Trusted contact'}</b><p>{user.emergency_phone || 'No phone number saved'}</p></div>{user.emergency_phone && <a className="icon-button call-contact" href={`tel:${user.emergency_phone}`} aria-label="Call trusted contact"><Phone size={18} /></a>}</div> : <div className="empty-state"><Users size={28} /><b>No trusted contact on this profile</b><p>Sign up with a trusted contact number, or use your phone's contacts directly.</p></div>}</section><section className="panel"><div className="panel-heading"><div className="heading-icon tone-blue"><MapPin size={19} /></div><div><h3>Nearest support</h3><p>Calculated from the latest available coordinates</p></div></div>{(nearestStation || nearest?.police_station) ? <div className="support-list-item"><Shield size={18} /><div><b>{(nearestStation || nearest.police_station).name}</b><small>{(nearestStation || nearest.police_station).distanceText || 'Nearest mapped station'}</small></div>{(nearestStation || nearest.police_station).phone && <a href={`tel:${(nearestStation || nearest.police_station).phone}`} className="icon-button"><Phone size={16} /></a>}</div> : null}{nearest?.hospital ? <div className="support-list-item"><Hospital size={18} /><div><b>{nearest.hospital.name}</b><small>{nearest.hospital.distanceText}</small></div>{nearest.hospital.phone && <a href={`tel:${nearest.hospital.phone}`} className="icon-button"><Phone size={16} /></a>}</div> : null}{!(nearestStation || nearest?.police_station) && !nearest?.hospital && <p className="helper-text">Support locations will appear once the backend returns nearby results.</p>}<a className="text-link" href={`https://www.google.com/maps/search/?api=1&query=${location.lat},${location.lng}`} target="_blank" rel="noreferrer"><MapPin size={15} /> Open current location in Maps</a></section></div><VoiceCheck user={user} location={location} connected={socketConnected} agentState={agentState} onAnalysis={setVoiceAnalysis} /><EvidencePanel initialTrackingId={agentState?.trackingId} /></div>}



      {tab === 'profile' && <div className="page-content narrow-page animate-fade"><section className="welcome-row"><div><span className="eyebrow">ACCOUNT & PREFERENCES</span><h1>Your profile</h1><p>Details currently available from your local backend account.</p></div></section><section className="panel profile-panel"><div className="profile-hero"><div className="avatar avatar-large">{userName.trim().slice(0, 1).toUpperCase()}</div><div><h2>{userName}</h2><p>{user?.demo ? 'Demo session — changes are not saved to an account.' : `Account ID ${user?.id ?? 'available'}`}</p><span className={`status-pill ${user?.demo ? '' : 'status-live'}`}><span />{user?.demo ? 'Demo' : 'Account loaded'}</span></div></div><div className="profile-fields"><div><small>Phone number</small><b>{user?.phone || user?.userPhone || 'Not provided'}</b></div><div><small>Emergency contact</small><b>{user?.emergency_name || 'Not configured'}</b></div><div><small>Emergency contact phone</small><b>{user?.emergency_phone || 'Not configured'}</b></div><div><small>Backend API</small><b className="profile-url">{API_BASE_URL}</b></div></div><div className="profile-footer"><p>Account and contact updates are not exposed by the current backend API.</p><button className="button button-ghost" onClick={onLogout}><LogOut size={16} /> Sign out</button></div></section><section className="panel connection-panel"><div className="panel-heading"><div className="heading-icon tone-green"><Radio size={19} /></div><div><h3>Connection status</h3><p>Live connection health from this browser</p></div></div><div className="connection-status-row"><span>Socket.IO</span><b className={socketConnected ? 'text-green' : 'text-rose'}>{socketConnected ? 'Connected' : 'Disconnected'}</b></div><div className="connection-status-row"><span>GPS</span><b>{locationStatus === 'live' ? 'Live location' : locationStatus === 'denied' ? 'Permission denied' : 'Approximate / unavailable'}</b></div><div className="connection-status-row"><span>Safe route engine</span><b>{routeHealth?.ready ? 'Dependencies ready' : 'Check backend setup'}</b></div><button className="button button-ghost" onClick={() => navigate('/analytics')}>View data diagnostics <ArrowRight size={16} /></button></section></div>}



      <footer className="app-footer"><span>SAKHI-SAHAYAK</span><span>Safety tools for informed decisions</span><span>Risk scores are heuristic, not guarantees.</span></footer>

    </main>

    {isSarthiAlarm && <div className="modal-backdrop"><section className="sarthi-modal"><div className="sarthi-modal-icon"><AlertTriangle size={30} /></div><span className="eyebrow">SARTHI CHECK-IN</span><h2>Are you okay?</h2><p>No meaningful GPS movement was detected. Confirm your safety before the countdown ends.</p><div className="sarthi-countdown" aria-live="polite">Emergency escalation in <strong>{checkInSeconds}s</strong></div><div className="modal-actions"><button className="button button-ghost" onClick={() => { setCheckInHandled(true); cancelSarthiAlarm(); }}>Dismiss reminder</button><button className="button button-primary" onClick={() => { setCheckInHandled(true); confirmSafe(); }}><CheckCircle2 size={17} /> I'm safe</button></div><button className="modal-emergency-link" onClick={() => { setCheckInHandled(true); cancelSarthiAlarm(); triggerSOS({ skipConfirm: true }); }}><Siren size={16} /> I need emergency help</button></section></div>}

  </div>;

}
