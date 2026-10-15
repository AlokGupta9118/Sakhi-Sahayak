import { createElement, useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ArrowLeft, Building2, Hospital, MapPin, Navigation, RefreshCw, Search, Shield, ShieldCheck, Train, Users } from 'lucide-react';
import { api, getApiError } from '../lib/api';

const layers = [
  { key: 'police_stations', label: 'Police stations', icon: Shield, tone: 'blue' },
  { key: 'hospitals', label: 'Hospitals', icon: Hospital, tone: 'rose' },
  { key: 'metro_stations', label: 'Metro stations', icon: Train, tone: 'slate' },
  { key: 'tactical_units', label: 'Support units', icon: ShieldCheck, tone: 'green' },
  { key: 'hostels_pgs', label: 'Hostels & PGs', icon: Building2, tone: 'amber' },
  { key: 'educational_institutions', label: 'Educational institutions', icon: Users, tone: 'violet' },
];

export default function Community({ user }) {
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [query, setQuery] = useState('');
  const [selected, setSelected] = useState('all');

  const load = useCallback(async () => {
    setLoading(true); setError('');
    try { const { data: response } = await api.get('/api/safety-data'); setData(response); }
    catch (err) { setError(getApiError(err, 'Could not load the safety network.')); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { void load(); }, [load]);

  const places = useMemo(() => {
    return layers.flatMap((layer) => (data?.[layer.key] || []).map((place, index) => ({ ...place, layer: layer.key, layerLabel: layer.label, tone: layer.tone, icon: layer.icon, id: place.id || `${layer.key}-${index}` })))
      .filter((place) => selected === 'all' || place.layer === selected)
      .filter((place) => `${place.name || ''} ${place.address || ''} ${place.description || ''} ${place.zone || ''}`.toLowerCase().includes(query.toLowerCase()));
  }, [data, selected, query]);

  return <div className="community-page"><header className="analytics-topbar"><button className="button button-ghost" onClick={() => navigate('/dashboard')}><ArrowLeft size={16} /> Back to dashboard</button><div className="community-user"><span className="avatar avatar-small">{(user?.name || 'S').slice(0, 1).toUpperCase()}</span><span>{user?.name || 'Traveler'}</span></div></header><main className="community-content"><section className="community-hero"><div><span className="eyebrow">LOCAL SAFETY NETWORK</span><h1>Support points around your city.</h1><p>Browse police stations, hospitals, transit and support locations from the backend's configured safety dataset.</p></div><div className="community-hero-icon"><Users size={27} /></div></section>
    {error && <div className="inline-error community-message"><span>{error}</span><button className="button button-ghost button-sm" onClick={load}>Retry</button></div>}
    <section className="community-summary"><div><small>Mapped support points</small><b>{loading ? '…' : places.length}</b></div><div><small>Source categories</small><b>{layers.filter((layer) => data?.[layer.key]?.length).length}</b></div><button className="button button-ghost" onClick={load} disabled={loading}><RefreshCw size={15} className={loading ? 'spin' : ''} /> Refresh data</button></section>
    <section className="community-tools"><div className="community-search"><Search size={17} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search a place, zone or description" /></div><div className="community-filters"><button className={selected === 'all' ? 'active' : ''} onClick={() => setSelected('all')}>All points</button>{layers.map((layer) => <button key={layer.key} className={selected === layer.key ? 'active' : ''} onClick={() => setSelected(layer.key)}>{layer.label}</button>)}</div></section>
    {loading ? <div className="community-loading"><RefreshCw size={22} className="spin" /><p>Loading mapped safety points…</p></div> : places.length ? <section className="community-place-grid">{places.map((place) => { const Icon = place.icon; const hasCoords = Number.isFinite(Number(place.lat)) && Number.isFinite(Number(place.lng)); return <article className="community-place-card" key={place.id}><div className={`community-place-icon tone-${place.tone}`}>{createElement(Icon, { size: 19 })}</div><div className="community-place-type">{place.layerLabel}</div><h3>{place.name || place.layerLabel}</h3><p>{place.description || place.address || place.zone || 'Listed in the configured safety dataset.'}</p>{place.address && <div className="community-place-address"><MapPin size={13} />{place.address}</div>}<div className="community-place-footer"><span>{place.zone || place.type || 'Mapped location'}</span>{hasCoords ? <a href={`https://www.google.com/maps/dir/?api=1&destination=${place.lat},${place.lng}`} target="_blank" rel="noreferrer"><Navigation size={14} /> Directions</a> : <span>Coordinates unavailable</span>}</div>{(place.phone || place.contact) && <a className="community-call-link" href={`tel:${place.phone || place.contact}`}>Call listed contact</a>}</article>; })}</section> : <div className="empty-state community-empty"><MapPin size={30} /><b>No matching locations</b><p>Try another search or choose a different category. This page only shows records present in the backend dataset.</p></div>}
    <p className="safety-footnote"><ShieldCheck size={15} /> Listing a location does not confirm current operating hours, availability, or safety. Check directly before relying on a service.</p></main></div>;
}
