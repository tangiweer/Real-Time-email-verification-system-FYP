import { useState, useRef } from 'react';
import { UploadCloud, CheckCircle2, AlertTriangle, XCircle, HelpCircle, Download, FileSpreadsheet } from 'lucide-react';
import { API_BASE, apiHeaders, apiFetch } from '../config';

export default function BulkUpload() {
  const [file, setFile] = useState(null);
  const [status, setStatus] = useState('idle'); // idle, uploading, processing, complete, error
  const [progress, setProgress] = useState(0);
  const [jobId, setJobId] = useState(null);
  const [summary, setSummary] = useState(null);
  
  const fileInputRef = useRef(null);
  const [isDragging, setIsDragging] = useState(false);

  const uploadFile = async (selectedFile) => {
    if (!selectedFile) return;
    
    setFile(selectedFile);
    setStatus('uploading');
    setProgress(0);
    setSummary(null);

    const formData = new FormData();
    formData.append('file', selectedFile);

    try {
      const response = await apiFetch(`${API_BASE}/jobs/upload`, {
        method: 'POST',
        headers: apiHeaders(),
        body: formData
      });
      
      if (!response.ok) throw new Error('Upload failed');
      
      const data = await response.json();
      setJobId(data.job_id);
      setStatus('processing');
      pollStatus(data.job_id);
    } catch (err) {
      console.error(err);
      setStatus('error');
    }
  };

  const handleFileSelect = (e) => {
    uploadFile(e.target.files[0]);
  };

  const handleDragOver = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(true);
  };

  const handleDragLeave = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
  };

  const handleDrop = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
    
    const droppedFile = e.dataTransfer.files[0];
    if (droppedFile) {
      uploadFile(droppedFile);
    }
  };

  const pollStatus = async (id) => {
    try {
      const res = await apiFetch(`${API_BASE}/jobs/${id}`, { headers: apiHeaders() });
      if (!res.ok) throw new Error('Could not retrieve job status');
      const data = await res.json();
      
      setProgress(data.progress_percent || 0);
      
      if (data.status === 'COMPLETED') {
        setStatus('complete');
        setSummary(data.results);
      } else if (data.status === 'FAILED') {
        setStatus('error');
      } else {
        setTimeout(() => pollStatus(id), 1000);
      }
    } catch (err) {
      console.error(err);
      setStatus('error');
    }
  };

  const downloadResults = async () => {
    if (!jobId) return;
    try {
      const response = await apiFetch(`${API_BASE}/jobs/${jobId}/download`, { headers: apiHeaders() });
      if (!response.ok) throw new Error('Could not download results');
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `verified_emails_${jobId}.csv`;
      link.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      console.error(err);
      setStatus('error');
    }
  };

  // Helper component for premium stat cards
  const PremiumStatCard = ({ title, value, icon: Icon, colorClass, bgColorClass, delay }) => (
    <div style={{
      background: 'rgba(255, 255, 255, 0.7)',
      backdropFilter: 'blur(12px)',
      borderRadius: '16px',
      padding: '1.25rem',
      display: 'flex',
      alignItems: 'center',
      gap: '1rem',
      border: '1px solid rgba(255, 255, 255, 0.8)',
      boxShadow: '0 4px 15px rgba(0, 0, 0, 0.02), inset 0 1px 0 rgba(255,255,255,1)',
      animation: `slideUpFade 0.5s ease-out ${delay}s both`,
      transition: 'transform 0.2s, box-shadow 0.2s',
      cursor: 'default'
    }}
    onMouseEnter={(e) => {
      e.currentTarget.style.transform = 'translateY(-2px)';
      e.currentTarget.style.boxShadow = '0 8px 25px rgba(0, 0, 0, 0.04), inset 0 1px 0 rgba(255,255,255,1)';
    }}
    onMouseLeave={(e) => {
      e.currentTarget.style.transform = 'none';
      e.currentTarget.style.boxShadow = '0 4px 15px rgba(0, 0, 0, 0.02), inset 0 1px 0 rgba(255,255,255,1)';
    }}
    >
      <div style={{
        width: '48px', height: '48px', borderRadius: '12px',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        background: `var(--${bgColorClass})`,
        color: `var(--${colorClass})`
      }}>
        <Icon size={24} strokeWidth={2.5} />
      </div>
      <div>
        <p style={{ fontSize: '0.85rem', fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>
          {title}
        </p>
        <p style={{ fontSize: '1.75rem', fontWeight: 800, color: 'var(--text-main)', lineHeight: 1.2 }}>
          {value}
        </p>
      </div>
    </div>
  );

  return (
    <>
      <style>{`
        @keyframes slideUpFade {
          from { opacity: 0; transform: translateY(15px); }
          to { opacity: 1; transform: translateY(0); }
        }
        @keyframes pulseBorder {
          0% { border-color: rgba(56, 189, 248, 0.3); }
          50% { border-color: rgba(56, 189, 248, 0.8); }
          100% { border-color: rgba(56, 189, 248, 0.3); }
        }
        .premium-dropzone {
          border: 2px dashed rgba(203, 213, 225, 0.8);
          border-radius: 24px;
          padding: 3.5rem 2rem;
          text-align: center;
          background: rgba(255, 255, 255, 0.4);
          backdrop-filter: blur(8px);
          cursor: pointer;
          transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
          display: flex;
          flex-direction: column;
          align-items: center;
          justify-content: center;
        }
        .premium-dropzone:hover, .premium-dropzone.dragging {
          background: rgba(255, 255, 255, 0.8);
          border-color: var(--brand-accent);
          transform: scale(1.01);
          box-shadow: 0 10px 40px -10px rgba(2, 132, 199, 0.15);
        }
        .premium-btn {
          background: var(--brand-main, #0f172a);
          color: white;
          border: none;
          padding: 1rem 2rem;
          border-radius: 14px;
          font-weight: 600;
          font-size: 1rem;
          cursor: pointer;
          transition: all 0.2s;
          display: flex;
          align-items: center;
          justify-content: center;
          gap: 0.75rem;
          box-shadow: 0 4px 14px rgba(15, 23, 42, 0.25);
        }
        .premium-btn:hover {
          background: #1e293b;
          transform: translateY(-2px);
          box-shadow: 0 6px 20px rgba(15, 23, 42, 0.3);
        }
      `}</style>

      <div className="grid-container" style={{ maxWidth: '850px', padding: '3rem 2rem' }}>
        <div style={{ marginBottom: '3rem', textAlign: 'center' }}>
          <h1 className="intro-title" style={{ fontSize: '2.75rem', marginBottom: '0.75rem' }}>
            Batch Processing <span>Studio</span>
          </h1>
          <p style={{ color: 'var(--text-muted)', fontSize: '1.1rem', maxWidth: '600px', margin: '0 auto' }}>
            Upload your datasets for massive-scale parallel verification. The engine handles up to 100,000 records asynchronously.
          </p>
        </div>
        
        <div style={{
          background: 'rgba(255, 255, 255, 0.5)',
          backdropFilter: 'blur(20px)',
          borderRadius: '32px',
          padding: '2.5rem',
          border: '1px solid rgba(255, 255, 255, 0.6)',
          boxShadow: '0 20px 40px -20px rgba(0,0,0,0.05), inset 0 1px 0 rgba(255,255,255,1)'
        }}>
          
          <div 
            className={`premium-dropzone ${isDragging ? 'dragging' : ''}`}
            onClick={() => fileInputRef.current.click()}
            onDragOver={handleDragOver}
            onDragEnter={handleDragOver}
            onDragLeave={handleDragLeave}
            onDrop={handleDrop}
            style={isDragging ? { animation: 'pulseBorder 1.5s infinite' } : {}}
          >
            <div style={{ 
              width: '80px', height: '80px', borderRadius: '24px', 
              background: 'linear-gradient(135deg, rgba(56, 189, 248, 0.1), rgba(129, 140, 248, 0.1))',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              marginBottom: '1.5rem', color: 'var(--brand-accent)'
            }}>
              {file ? <FileSpreadsheet size={40} /> : <UploadCloud size={40} />}
            </div>
            <h3 style={{ fontSize: '1.25rem', fontWeight: 600, color: 'var(--text-main)', marginBottom: '0.5rem' }}>
              {file ? file.name : "Drag & drop your CSV file"}
            </h3>
            <p style={{ color: 'var(--text-muted)', fontSize: '0.95rem' }}>
              {file ? `Ready to process ${(file.size / 1024 / 1024).toFixed(2)} MB` : "or click to browse local files (max 50MB)"}
            </p>
            <input 
              type="file" 
              ref={fileInputRef} 
              accept=".csv" 
              style={{ display: 'none' }} 
              onChange={handleFileSelect} 
            />
          </div>
          
          {status !== 'idle' && (
            <div style={{ 
              marginTop: '2.5rem', 
              animation: 'slideUpFade 0.4s ease-out forwards'
            }}>
              <div style={{ 
                display: 'flex', justifyContent: 'space-between', alignItems: 'center', 
                marginBottom: '1rem', padding: '0 0.5rem'
              }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                  <div style={{ 
                    width: '10px', height: '10px', borderRadius: '50%', 
                    background: status === 'complete' ? 'var(--status-valid)' : 'var(--brand-accent)',
                    boxShadow: status !== 'complete' ? '0 0 10px var(--brand-accent)' : 'none'
                  }}></div>
                  <span style={{ fontWeight: 600, color: 'var(--text-main)', fontSize: '1.05rem' }}>
                    {status === 'error' ? 'Processing Failed' : status === 'complete' ? 'Analysis Complete' : 'Engine Running...'}
                  </span>
                </div>
                <span style={{ fontWeight: 700, fontSize: '1.1rem', color: 'var(--brand-accent)' }}>
                  {progress}%
                </span>
              </div>

              <div style={{ 
                height: '8px', background: 'rgba(0,0,0,0.06)', borderRadius: '99px', overflow: 'hidden',
                boxShadow: 'inset 0 1px 2px rgba(0,0,0,0.05)'
              }}>
                <div style={{ 
                  height: '100%', 
                  background: 'linear-gradient(90deg, #38bdf8, #818cf8)',
                  width: `${progress}%`,
                  borderRadius: '99px',
                  transition: 'width 0.4s cubic-bezier(0.4, 0, 0.2, 1)'
                }}></div>
              </div>
              
              {summary && (
                <div style={{ 
                  display: 'grid', 
                  gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', 
                  gap: '1.25rem', 
                  marginTop: '2.5rem' 
                }}>
                  <PremiumStatCard title="Valid" value={summary.valid} icon={CheckCircle2} colorClass="status-valid" bgColorClass="status-valid-bg" delay={0.1} />
                  <PremiumStatCard title="Invalid" value={summary.invalid} icon={XCircle} colorClass="status-invalid" bgColorClass="status-invalid-bg" delay={0.2} />
                  <PremiumStatCard title="Suspicious" value={summary.suspicious} icon={AlertTriangle} colorClass="status-warning" bgColorClass="status-warning-bg" delay={0.3} />
                  <PremiumStatCard title="Uncertain" value={summary.uncertain} icon={HelpCircle} colorClass="status-uncertain" bgColorClass="status-uncertain-bg" delay={0.4} />
                </div>
              )}
              
              {status === 'complete' && (
                <div style={{ marginTop: '2.5rem', animation: 'slideUpFade 0.5s ease-out 0.5s both', display: 'flex', justifyContent: 'center' }}>
                  <button className="premium-btn" onClick={downloadResults}>
                    <Download size={20} />
                    Download Cleaned Dataset
                  </button>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </>
  );
}
