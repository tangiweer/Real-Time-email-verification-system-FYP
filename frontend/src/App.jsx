import { BrowserRouter as Router, Navigate, Routes, Route } from 'react-router-dom';
import Sidebar from './components/Sidebar';
import TopNav from './components/TopNav';
import Dashboard from './pages/Dashboard';
import Verifications from './pages/Verifications';
import BulkUpload from './pages/BulkUpload';
import RegistrationDemo from './pages/RegistrationDemo';
import LiveDashboard from './pages/LiveDashboard';
import './App.css';

function AdminArea() {
  return (
    <>
      <div className="ambient-blobs"></div>
      <Sidebar />
      <main className="main-wrapper">
        <TopNav />
        <div className="content">
          <Routes>
            <Route index element={<Dashboard />} />
            <Route path="verifications" element={<Verifications />} />
            <Route path="bulk" element={<BulkUpload />} />
            <Route path="live" element={<LiveDashboard />} />
            <Route path="*" element={<Navigate to="/dashboard" replace />} />
          </Routes>
        </div>
      </main>
    </>
  );
}

function App() {
  return (
    <Router>
      <Routes>
        <Route path="/" element={<RegistrationDemo />} />
        <Route path="/register" element={<Navigate to="/" replace />} />
        <Route path="/dashboard/*" element={<AdminArea />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Router>
  );
}

export default App;
