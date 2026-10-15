import { BrowserRouter, Routes, Route, Navigate, useLocation, useNavigate } from 'react-router-dom';
import { useEffect, useState } from 'react';
import Login from './components/Login';
import Dashboard from './components/Dashboard';
import FamilyDashboard from './components/FamilyDashboard';
import Analytics from './components/Analytics';
import Community from './components/Community';

const USER_KEY = 'sakhi-sahayak-user';

function AppRoutes() {
  const [user, setUser] = useState(() => {
    try { return JSON.parse(localStorage.getItem(USER_KEY) || 'null'); } catch { return null; }
  });
  const location = useLocation();
  const navigate = useNavigate();

  useEffect(() => {
    if (user) localStorage.setItem(USER_KEY, JSON.stringify(user));
    else localStorage.removeItem(USER_KEY);
  }, [user]);

  const login = (userData) => {
    setUser(userData);
    navigate('/dashboard', { replace: true });
  };
  const logout = () => {
    setUser(null);
    navigate('/login', { replace: true, state: { from: location.pathname } });
  };

  return (
    <Routes>
      <Route path="/login" element={user ? <Navigate to="/dashboard" replace /> : <Login onLogin={login} />} />
      <Route path="/dashboard" element={user ? <Dashboard user={user} onLogout={logout} /> : <Navigate to="/login" replace />} />
      <Route path="/analytics" element={user ? <Analytics user={user} onLogout={logout} /> : <Navigate to="/login" replace />} />
      <Route path="/community" element={user ? <Community user={user} onLogout={logout} /> : <Navigate to="/login" replace />} />
      <Route path="/family" element={user ? <FamilyDashboard /> : <Navigate to="/login" replace />} />
      <Route path="*" element={<Navigate to={user ? '/dashboard' : '/login'} replace />} />
    </Routes>
  );
}

export default function App() {
  return <BrowserRouter><AppRoutes /></BrowserRouter>;
}
