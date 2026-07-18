import React, { useState, useEffect, useRef } from "react";
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from "recharts";

export default function LiveDashboard() {
  const [events, setEvents] = useState([]);
  const [stats, setStats] = useState({ valid: 0, invalid: 0, suspicious: 0, uncertain: 0 });
  const ws = useRef(null);

  useEffect(() => {
    // Connect to FastAPI websocket
    ws.current = new WebSocket("ws://localhost:8000/ws/live-pipeline");

    ws.current.onmessage = (event) => {
      const data = JSON.parse(event.data);
      
      setEvents((prev) => {
        const newEvents = [data, ...prev].slice(0, 50); // Keep last 50
        return newEvents;
      });

      setStats((prev) => ({
        ...prev,
        [data.status]: (prev[data.status] || 0) + 1,
      }));
    };

    return () => {
      if (ws.current) {
        ws.current.close();
      }
    };
  }, []);

  const chartData = [
    { name: "Valid", value: stats.valid },
    { name: "Invalid", value: stats.invalid },
    { name: "Suspicious", value: stats.suspicious },
    { name: "Uncertain", value: stats.uncertain },
  ];

  return (
    <div className="grid-container">
      <h1 className="intro-title" style={{ marginBottom: "0.5rem" }}>Live Pipeline Dashboard</h1>
      <p style={{ color: "var(--text-muted)", marginBottom: "2rem", fontSize: "1.1rem" }}>
        Real-time view of the verification gateway powered by WebSockets.
      </p>

      <div className="stat-cards-grid" style={{ marginBottom: "2rem" }}>
        <div className="stat-card valid">
          <span className="label">Valid</span>
          <span className="value">{stats.valid}</span>
        </div>
        <div className="stat-card invalid">
          <span className="label">Invalid</span>
          <span className="value">{stats.invalid}</span>
        </div>
        <div className="stat-card suspicious">
          <span className="label">Suspicious (ML)</span>
          <span className="value">{stats.suspicious}</span>
        </div>
        <div className="stat-card uncertain">
          <span className="label">Uncertain</span>
          <span className="value">{stats.uncertain}</span>
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(400px, 1fr))", gap: "2rem" }}>
        <div className="glass-card" style={{ padding: "1.5rem" }}>
          <div className="console-header">
            <h3>Real-time Results</h3>
          </div>
          <div style={{ height: "350px", marginTop: "1rem" }}>
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={chartData}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--border-color)" />
                <XAxis dataKey="name" stroke="var(--text-muted)" tick={{ fill: 'var(--text-muted)' }} />
                <YAxis stroke="var(--text-muted)" tick={{ fill: 'var(--text-muted)' }} />
                <Tooltip 
                  contentStyle={{ 
                    backgroundColor: "var(--glass-bg)", 
                    borderRadius: "12px", 
                    border: "1px solid var(--glass-border)",
                    backdropFilter: "blur(10px)",
                    boxShadow: "0 10px 25px rgba(0,0,0,0.1)",
                    color: "var(--text-main)"
                  }} 
                />
                <Line 
                  type="monotone" 
                  dataKey="value" 
                  stroke="url(#colorUv)" 
                  strokeWidth={4} 
                  dot={{ r: 6, fill: "var(--brand-primary)", strokeWidth: 2, stroke: "#fff" }} 
                  activeDot={{ r: 8, fill: "var(--brand-accent)", strokeWidth: 0 }} 
                />
                <defs>
                  <linearGradient id="colorUv" x1="0" y1="0" x2="1" y2="0">
                    <stop offset="0%" stopColor="var(--brand-primary)" />
                    <stop offset="100%" stopColor="var(--brand-accent)" />
                  </linearGradient>
                </defs>
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="glass-card" style={{ padding: "1.5rem", display: "flex", flexDirection: "column" }}>
          <div className="console-header">
            <h3>Live Event Stream</h3>
          </div>
          <div style={{ 
            overflowY: "auto", 
            height: "350px", 
            marginTop: "1rem", 
            display: "flex", 
            flexDirection: "column", 
            gap: "0.75rem",
            paddingRight: "0.5rem"
          }}>
            {events.length === 0 ? (
              <div style={{ 
                height: "100%", 
                display: "flex", 
                alignItems: "center", 
                justifyContent: "center",
                flexDirection: "column",
                opacity: 0.6
              }}>
                <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" style={{ marginBottom: "1rem", color: "var(--text-muted)" }}>
                  <path d="M22 12h-4l-3 9L9 3l-3 9H2" />
                </svg>
                <p style={{ color: "var(--text-muted)", fontSize: "0.95rem", textAlign: "center" }}>
                  Awaiting verifications...<br/>Run a bulk job to see real-time data.
                </p>
              </div>
            ) : (
              events.map((ev, i) => (
                <div key={i} style={{ 
                  display: "flex", 
                  justifyContent: "space-between", 
                  alignItems: "center", 
                  padding: "1.25rem", 
                  background: "rgba(255,255,255,0.7)", 
                  borderRadius: "16px",
                  border: "1px solid rgba(255,255,255,0.8)",
                  boxShadow: "0 2px 10px rgba(0,0,0,0.02)",
                  transition: "transform 0.2s cubic-bezier(0.4, 0, 0.2, 1), box-shadow 0.2s",
                  cursor: "default",
                  animation: "fadeIn 0.3s ease-out"
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.transform = "translateX(5px) scale(1.01)";
                  e.currentTarget.style.boxShadow = "0 8px 20px rgba(0,0,0,0.06)";
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.transform = "none";
                  e.currentTarget.style.boxShadow = "0 2px 10px rgba(0,0,0,0.02)";
                }}
                >
                  <div>
                    <p style={{ fontWeight: "600", fontSize: "0.95rem", color: "var(--text-main)" }}>{ev.email}</p>
                    <p style={{ fontSize: "0.8rem", color: "var(--text-muted)", marginTop: "0.25rem", display: "flex", alignItems: "center", gap: "0.3rem" }}>
                      <span style={{ 
                        display: "inline-block", 
                        width: "6px", 
                        height: "6px", 
                        borderRadius: "50%", 
                        background: ev.confidence > 0.8 ? "var(--status-valid)" : ev.confidence > 0.5 ? "var(--status-warning)" : "var(--status-invalid)"
                      }}></span>
                      Confidence: {(ev.confidence * 100).toFixed(1)}%
                    </p>
                  </div>
                  <span className="badge" style={{
                    background: ev.status === "valid" ? "var(--status-valid-bg)" : 
                               ev.status === "invalid" ? "var(--status-invalid-bg)" :
                               ev.status === "suspicious" ? "var(--status-warning-bg)" : "var(--status-uncertain-bg)",
                    color: ev.status === "valid" ? "var(--status-valid)" : 
                           ev.status === "invalid" ? "var(--status-invalid)" :
                           ev.status === "suspicious" ? "var(--status-warning)" : "var(--status-uncertain)",
                    textTransform: "uppercase",
                    letterSpacing: "0.5px",
                    padding: "0.4rem 1rem"
                  }}>
                    {ev.status}
                  </span>
                </div>
              ))
            )}
            <style>{`
              @keyframes fadeIn {
                from { opacity: 0; transform: translateY(10px); }
                to { opacity: 1; transform: translateY(0); }
              }
            `}</style>
          </div>
        </div>
      </div>
    </div>
  );
}
