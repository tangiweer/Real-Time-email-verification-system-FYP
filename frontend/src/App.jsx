import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';
import Sidebar from './components/Sidebar';
import TopNav from './components/TopNav';
import Dashboard from './pages/Dashboard';
import Verifications from './pages/Verifications';
import BulkUpload from './pages/BulkUpload';
import RegistrationDemo from './pages/RegistrationDemo';
import LiveDashboard from './pages/LiveDashboard';
import './App.css';

function App() {
  return (
    <Router>
      <Routes>
        <Route path="/register" element={<RegistrationDemo />} />
        
        <Route path="*" element={
          <>
            <div className="ambient-blobs"></div>
            <Sidebar />
            <main className="main-wrapper">
              <TopNav />
              <div className="content">
                <Routes>
                  <Route path="/" element={<Dashboard />} />
                  <Route path="/verifications" element={<Verifications />} />
                  <Route path="/bulk" element={<BulkUpload />} />
                  <Route path="/live" element={<LiveDashboard />} />
                </Routes>
              </div>
            </main>
          </>
        } />
      </Routes>
    </Router>
  );
}

export default App;
