import { NavLink } from 'react-router-dom';
import { LayoutDashboard, CheckCircle, UploadCloud, Activity } from 'lucide-react';

export default function Sidebar() {
  return (
    <aside className="sidebar">
      <div className="sidebar-header">
        <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" width="28" height="28">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2"
            d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z">
          </path>
        </svg>
        <h2>Email Verification<br/>Framework</h2>
      </div>
      <nav className="sidebar-nav">
        <NavLink 
          to="/" 
          className={({ isActive }) => isActive ? "nav-item active" : "nav-item"}
        >
          <LayoutDashboard size={20} />
          Dashboard
        </NavLink>
        <NavLink 
          to="/verifications" 
          className={({ isActive }) => isActive ? "nav-item active" : "nav-item"}
        >
          <CheckCircle size={20} />
          Verifications
        </NavLink>
        <NavLink 
          to="/bulk" 
          className={({ isActive }) => isActive ? "nav-item active" : "nav-item"}
        >
          <UploadCloud size={20} />
          Bulk Upload
        </NavLink>
        <NavLink 
          to="/live" 
          className={({ isActive }) => isActive ? "nav-item active" : "nav-item"}
        >
          <Activity size={20} />
          Live Pipeline
        </NavLink>
      </nav>
    </aside>
  );
}
