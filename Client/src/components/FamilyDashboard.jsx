import { useCallback, useEffect, useMemo, useState } from 'react';
import { Activity, AlertTriangle, ArrowLeft, CheckCircle2, HeartPulse, MapPin, Radio, RefreshCw, ShieldCheck, Users } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import SarthiMap from './SarthiMap';
import { api, getApiError } from '../lib/api';
import { socket } from '../lib/socket';

export default function FamilyDashboard() {
  const navigate = useNavigate();
  const [trackedUsers, setTrackedUsers] = useState({});
  const [safetyData, setSafetyData] = useState(null);
  const [connected, setConnected] = useState(socket.connected);
  const [error, setError] = useState('');
  const [lastAlert, setLastAlert] = useState(null);
  const [loading, setLoading] = useState(true);

  const loadData = useCallback(async () => {
    setLoading(true); setError('');
    try { const { data } = await api.get('/api/safety-data'); setSafetyData(data); }
    catch (err) { setError(getApiError(err, 'Safety map data could not be loaded.')); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => {
    void loadData();
    const onConnect = () => setConnected(true);
    const onDisconnect = () => setConnected(false);
    const onSync = (data) => setTrackedUsers(data || {});
    const onEmergency = (payload) => setLastAlert({ ...payload, receivedAt: new Date().toISOString() });
    socket.on('connect', onConnect); socket.on('disconnect', onDisconnect);
    socket.on('family-dashboard-sync', onSync); socket.on('emergency-broadcast-sent', onEmergency);
    if (!socket.connected) socket.connect();
    return () => { socket.off('connect', onConnect); socket.off('disconnect', onDisconnect); socket.off('family-dashboard-sync', onSync); socket.off('emergency-broadcast-sent', onEmergency); };
  }, [loadData]);

  const entries = useMemo(() => Object.entries(trackedUsers).filter(([, value]) => Number.isFinite(Number(value?.lat)) && Number.isFinite(Number(value?.lng))), [trackedUsers]);
  const firstLocation = entries.length ? entries[0][1] : { lat: 21.1458, lng: 79.0882, isApproximate: true };
  const sosCount = entries.filter(([, value]) => value.isSOS).length;

  return <main className="family-page">
    <header className="family-topbar"><button className="brand-lockup" onClick={() => navigate('/login')}><span className="brand-mark"><ShieldCheck size={22} /></span><span>Sakhi<span className="brand-accent">-Sahayak</span><small>TRUSTED FAMILY VIEW</small></span></button><div className="family-top-actions"><span className={`connection-chip ${connected ? 'connected' : 'disconnected'}`}><span />{connected ? 'Live connection' : 'Reconnecting'}</span><button className="button button-ghost button-sm" onClick={loadData} disabled={loading}><RefreshCw size={15} className={loading ? 'spin' : ''} /> Refresh map</button><button className="button button-ghost button-sm" onClick={() => navigate('/login')}><ArrowLeft size={15} /> Exit view</button></div></header>
    <div className="family-content"><section className="family-intro"><div><span className="eyebrow"><span className="eyebrow-dot" /> PRIVATE LIVE VIEW</span><h1>Stay connected to the people you care about.</h1><p>This view shows locations shared by connected sessions. It does not add a person to your family group automatically.</p></div><div className="family-intro-icon"><HeartPulse size={26} /></div></section>
      {error && <div className="inline-error family-error"><AlertTriangle size={16} /><span>{error}</span><button className="button button-ghost button-sm" onClick={loadData}>Retry</button></div>}
      {lastAlert && <div className="family-alert"><AlertTriangle size={19} /><div><b>Emergency event received</b><p>{lastAlert.trackingId ? `Tracking ID: ${lastAlert.trackingId}` : 'A connected client reported an emergency event.'} — {new Date(lastAlert.receivedAt).toLocaleTimeString()}</p></div></div>}
      <section className="family-stats"><div className="family-stat"><span className="family-stat-icon tone-blue"><Users size={19} /></span><div><small>Live sessions</small><b>{entries.length}</b></div></div><div className="family-stat"><span className="family-stat-icon tone-green"><Radio size={19} /></span><div><small>Connection</small><b>{connected ? 'Connected' : 'Reconnecting'}</b></div></div><div className="family-stat"><span className="family-stat-icon tone-rose"><AlertTriangle size={19} /></span><div><small>Active SOS flags</small><b className={sosCount ? 'text-rose' : ''}>{sosCount}</b></div></div></section>
      <section className="family-workspace"><aside className="family-travelers panel"><div className="panel-heading"><div className="heading-icon tone-blue"><Users size={19} /></div><div><h3>Shared travelers</h3><p>Updates arrive over Socket.IO</p></div></div>{entries.length ? <div className="traveler-list">{entries.map(([id, traveler]) => <article className={`traveler-card ${traveler.isSOS ? 'traveler-alert' : ''}`} key={id}><div className="traveler-avatar">{(traveler.userName || 'T').slice(0, 1).toUpperCase()}</div><div className="traveler-copy"><b>{traveler.userName || `Traveler ${id.slice(0, 5)}`}</b><small><MapPin size={12} /> {Number(traveler.lat).toFixed(4)}, {Number(traveler.lng).toFixed(4)}</small><small>{traveler.timestamp ? `Updated ${new Date(traveler.timestamp).toLocaleTimeString()}` : 'Location received'}</small></div>{traveler.isSOS ? <span className="sos-tag">SOS</span> : <span className="live-tag"><span /> Live</span>}</article>)}</div> : <div className="family-empty"><div><Users size={25} /></div><b>Waiting for a shared location</b><p>When a traveler opens the app, grants location permission and connects, their latest shared location appears here.</p></div>}<div className="family-privacy-note"><ShieldCheck size={15} /><span>Only sessions connected to this backend are visible. This is not a persistent family roster.</span></div></aside>
        <section className="family-map-panel"><div className="family-map-heading"><div><b>Shared locations map</b><small>Safety layers from the configured dataset</small></div><span className={`status-pill ${connected ? 'status-live' : ''}`}><span />{connected ? 'Live updates' : 'Offline'}</span></div><div className="family-map"><SarthiMap location={firstLocation} trackedUsers={trackedUsers} safetyData={safetyData} dangerZones={safetyData?.danger_zones || []} layers={{ dangerZones: true, blackSpots: true, policeStations: true, hospitals: true, metroStations: false, safeZones: false }} /></div><p className="family-map-caption"><CheckCircle2 size={14} /> {loading ? 'Loading map data…' : 'Map points are based on the backend safety dataset.'}</p></section></section>
      <div className="family-footer"><Activity size={15} /> Location sharing depends on browser permissions, network connectivity, and the traveler keeping the app connected. <a href="tel:112">Emergency help · 112</a></div>
    </div>
  </main>;
}
