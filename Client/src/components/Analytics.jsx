import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Activity, AlertTriangle, ArrowLeft, CheckCircle2, Database, DownloadCloud, MapPin, RefreshCw, Shield, Waypoints } from 'lucide-react';
import { api, getApiError } from '../lib/api';

export default function Analytics({ user, onLogout }) {
  const navigate = useNavigate();
  const [metrics, setMetrics] = useState(null);
  const [health, setHealth] = useState(null);
  const [loading, setLoading] = useState(true);
  const [regenerating, setRegenerating] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');

  const load = useCallback(async () => {
    setLoading(true); setError('');
    try {
      const [metricResult, healthResult] = await Promise.all([api.get('/api/safety-metrics'), api.get('/api/safe-route/health')]);
      setMetrics(metricResult.data); setHealth(healthResult.data);
    } catch (err) { setError(getApiError(err, 'Could not load backend metrics.')); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { void load(); }, [load]);

  const regenerate = async () => {
    if (!window.confirm('Regenerate map layers from the source workbook? This may take a while and will replace the generated safety data.')) return;
    setRegenerating(true); setError(''); setMessage('');
    try {
      const { data } = await api.post('/api/safety-data/regenerate', {}, { timeout: 180000 });
      setMessage(`Safety data regenerated. ${data.source_records ?? '—'} source records, ${data.danger_zone_clusters ?? '—'} clusters.`);
      await load();
    } catch (err) { setError(getApiError(err, 'Safety data regeneration failed.')); }
    finally { setRegenerating(false); }
  };

  const categories = Object.entries(metrics?.category_counts || {}).sort((a, b) => Number(b[1]) - Number(a[1]));
  const maxCategory = Math.max(1, ...categories.map(([, value]) => Number(value) || 0));
  const fmtDate = metrics?.generated_at ? new Date(metrics.generated_at).toLocaleString() : 'Not available';

  return <div className="analytics-page">
    <header className="analytics-topbar"><button className="button button-ghost" onClick={() => navigate('/dashboard')}><ArrowLeft size={16} /> Back to dashboard</button><div className="analytics-top-actions"><span className="connection-chip"><span /> {user?.name || 'Sakhi-Sahayak'}</span><button className="button button-ghost" onClick={load} disabled={loading}><RefreshCw size={15} className={loading ? 'spin' : ''} /> Refresh</button>{onLogout && <button className="button button-ghost" onClick={onLogout}>Sign out</button>}</div></header>
    <main className="analytics-content"><section className="welcome-row"><div><span className="eyebrow">BACKEND & DATA DIAGNOSTICS</span><h1>Safety data insights</h1><p>Live metrics returned by the geospatial backend—no placeholder performance claims.</p></div><button className="button button-primary" onClick={regenerate} disabled={regenerating}><DownloadCloud size={16} />{regenerating ? 'Regenerating…' : 'Regenerate data'}</button></section>
      {error && <div className="inline-error analytics-message"><AlertTriangle size={16} /><span>{error}</span></div>}{message && <div className="inline-notice analytics-message"><CheckCircle2 size={16} /><span>{message}</span></div>}
      <section className="analytics-kpis"><div className="analytics-kpi"><span className="tone-blue"><Database size={20} /></span><small>Source records</small><b>{loading ? '…' : metrics?.source_records ?? '—'}</b><p>Records in source workbook</p></div><div className="analytics-kpi"><span className="tone-green"><CheckCircle2 size={20} /></span><small>Coordinate coverage</small><b>{loading ? '…' : `${metrics?.coordinate_coverage_percent ?? '—'}%`}</b><p>{metrics?.records_with_valid_coordinates ?? '—'} records with valid coordinates</p></div><div className="analytics-kpi"><span className="tone-violet"><Waypoints size={20} /></span><small>Risk clusters</small><b>{loading ? '…' : metrics?.danger_zone_clusters ?? '—'}</b><p>Generated from the supplied records</p></div><div className="analytics-kpi"><span className="tone-rose"><MapPin size={20} /></span><small>Source categories</small><b>{loading ? '…' : metrics?.source_category_count ?? '—'}</b><p>Distinct source categories</p></div></section>
      <section className="analytics-main-grid"><article className="panel category-panel"><div className="panel-heading"><div className="heading-icon tone-violet"><Activity size={19} /></div><div><h3>Source records by category</h3><p>Counts from the generated safety-data metadata.</p></div></div>{categories.length ? <div className="category-chart">{categories.map(([name, value]) => <div className="category-row" key={name}><div className="category-label"><span>{name.replaceAll('_', ' ')}</span><b>{value}</b></div><div className="category-track"><div style={{ width: `${Math.max(2, (Number(value) / maxCategory) * 100)}%` }} /></div></div>)}</div> : <div className="empty-state"><Database size={26} /><b>{loading ? 'Loading metrics…' : 'No category counts returned'}</b><p>Start the backend and verify that safety_data.json exists.</p></div>}</article>
        <div className="analytics-side"><article className="panel"><div className="panel-heading"><div className="heading-icon tone-green"><Shield size={19} /></div><div><h3>Route engine</h3><p>Readiness check does not download the graph.</p></div></div><div className="engine-status"><span className={`engine-status-icon ${health?.ready ? 'ready' : 'not-ready'}`}>{health?.ready ? <CheckCircle2 size={19} /> : <AlertTriangle size={19} />}</span><div><b>{health?.ready ? 'Dependencies ready' : 'Needs attention'}</b><small>{health?.planner_initialized ? 'Planner initialized' : 'Planner initializes on first route request'}</small></div></div><div className="diagnostic-row"><span>Configured area</span><b>{health?.location_name || '—'}</b></div><div className="diagnostic-row"><span>Safety data file</span><b>{health?.safety_data_exists ? 'Found' : 'Missing'}</b></div><div className="diagnostic-row"><span>Cached road graph</span><b>{health?.graph_cache_exists ? 'Found' : 'Not downloaded'}</b></div>{health?.missing_dependencies?.length > 0 && <div className="dependency-warning"><AlertTriangle size={15} /> Missing: {health.missing_dependencies.join(', ')}</div>}</article>
          <article className="panel"><div className="panel-heading"><div className="heading-icon tone-blue"><Database size={19} /></div><div><h3>Dataset metadata</h3><p>Current generated safety data.</p></div></div><div className="diagnostic-row"><span>Generated at</span><b>{fmtDate}</b></div><div className="diagnostic-row"><span>Source file</span><b>{metrics?.source_file || '—'}</b></div><div className="metric-disclaimer"><AlertTriangle size={15} /><p>{metrics?.model_evaluation_note || 'Dataset counts and coordinate coverage are not model accuracy metrics.'}</p></div></article></div></section>
      <p className="safety-footnote"><AlertTriangle size={15} /> Do not report accuracy, precision, recall, or real-world incident reduction unless independently labeled evaluation data and a repeatable evaluation are available. Route scores are heuristic decision-support measures.</p>
    </main>
  </div>;
}
