import React, { useState, useEffect, useRef } from "react";
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from "recharts";
import { API_BASE, WS_BASE, apiFetch } from "../config";

export default function LiveDashboard() {
  const [events, setEvents] = useState([]);
  const [stats, setStats] = useState({ valid: 0, invalid: 0, suspicious: 0, uncertain: 0 });
  const [connectionState, setConnectionState] = useState("connecting");
  const [connectionError, setConnectionError] = useState("");
  const ws = useRef(null);
  const retryTimer = useRef(null);

  useEffect(() => {
    let disposed = false;
    let attempts = 0;

    // The token is issued from the authenticated HTTP-only browser session,
    // then used once for the WebSocket handshake.
    const connect = async () => {
      if (disposed) return;
      setConnectionState("connecting");
      setConnectionError("");

      try {
        const response = await apiFetch(`${API_BASE}/admin/ws-token`);
        if (!response.ok) {
          throw new Error(response.status === 401
            ? "Administrator access is required. Save an API key on the Dashboard."
            : "Could not create a live-stream session.");
        }
        const { token } = await response.json();
        if (!token) throw new Error("The server did not provide a WebSocket token.");
        if (disposed) return;

        const socket = new WebSocket(`${WS_BASE}/ws/live-pipeline?token=${encodeURIComponent(token)}`);
        ws.current = socket;
        socket.onopen = () => {
          attempts = 0;
          setConnectionState("connected");
        };
        socket.onmessage = (event) => {
          try {
            const data = JSON.parse(event.data);
            if (!data.status) return;
            setEvents((prev) => [data, ...prev].slice(0, 50));
            setStats((prev) => ({ ...prev, [data.status]: (prev[data.status] || 0) + 1 }));
          } catch {
            // Ignore malformed messages; later events can still be displayed.
          }
        };
        socket.onerror = () => setConnectionState("disconnected");
        socket.onclose = () => {
          if (disposed) return;
          setConnectionState("disconnected");
          attempts += 1;
          retryTimer.current = window.setTimeout(connect, Math.min(1000 * 2 ** attempts, 15000));
        };
      } catch (error) {
        if (disposed) return;
        setConnectionState("error");
        setConnectionError(error.message || "Unable to connect to the live pipeline.");
        // Authentication needs user action; transient backend/network failures
        // should recover on their own.
        if (!String(error.message).includes("Administrator access is required")) {
          attempts += 1;
          retryTimer.current = window.setTimeout(connect, Math.min(1000 * 2 ** attempts, 15000));
        }
      }
    };
    connect();

    return () => {
      disposed = true;
      window.clearTimeout(retryTimer.current);
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

  const stagesFor = (event) => [
    ["syntax", "Syntax"],
    ["dns", "DNS / MX"],
    ["ml", "ML risk"],
    ["smtp", "SMTP"],
  ].map(([key, label]) => {
    const duration = event.execution_times?.[key];
    const isDecisionLayer = event.failed_layer === key;
    const outcome = duration === undefined
      ? "Skipped"
      : isDecisionLayer && event.status === "invalid" ? "Rejected"
      : isDecisionLayer && event.status === "uncertain" ? "Inconclusive"
      : isDecisionLayer && event.status === "suspicious" ? "Flagged"
      : "Passed";
    return { key, label, duration, outcome };
  });

  return (
    <div className="grid-container">
      <h1 className="intro-title" style={{ marginBottom: "0.5rem" }}>Live Pipeline Dashboard</h1>
      <p style={{ color: "var(--text-muted)", marginBottom: "2rem", fontSize: "1.1rem" }}>
        Real-time view of the verification gateway powered by WebSockets.
      </p>
      <p style={{ color: connectionState === "connected" ? "var(--status-valid)" : "var(--text-muted)", marginTop: "-1.3rem", marginBottom: "1.5rem", fontSize: "0.9rem" }}>
        <span aria-hidden="true">● </span>
        {connectionState === "connected" ? "Live stream connected" : connectionState === "connecting" ? "Connecting to live stream…" : connectionError || "Reconnecting to live stream…"}
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
              <BarChart data={chartData}>
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
                <Bar
                  dataKey="value" 
                  fill="var(--brand-primary)"
                  radius={[8, 8, 0, 0]}
                />
              </BarChart>
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
                  Awaiting verifications...<br/>Configure an API key on the dashboard, then run a verification.
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
                    {ev.source === "registration" && (
                      <p style={{ fontSize: "0.75rem", color: "var(--text-muted)", marginTop: "0.25rem" }}>Registration attempt</p>
                    )}
                    {ev.source === "bulk" && (
                      <p style={{ fontSize: "0.75rem", color: "var(--text-muted)", marginTop: "0.25rem" }}>Bulk verification</p>
                    )}
                    {ev.status === "invalid" && ev.reasons?.length > 0 && (
                      <p style={{ fontSize: "0.8rem", color: "var(--status-invalid)", marginTop: "0.5rem", maxWidth: "440px" }}>
                        Reason: {ev.reasons.join(" ")}
                      </p>
                    )}
                    <div style={{ display: "flex", flexWrap: "wrap", gap: "0.35rem", marginTop: "0.75rem" }}>
                      {stagesFor(ev).map((stage) => (
                        <span key={stage.key} title={`${stage.label}: ${stage.outcome}${stage.duration !== undefined ? ` (${stage.duration} ms)` : ""}`} style={{
                          fontSize: "0.7rem", padding: "0.25rem 0.45rem", borderRadius: "999px",
                          color: stage.outcome === "Passed" ? "var(--status-valid)" : stage.outcome === "Skipped" ? "var(--text-muted)" : "var(--status-warning)",
                          background: stage.outcome === "Passed" ? "var(--status-valid-bg)" : "rgba(148,163,184,0.14)",
                        }}>
                          {stage.label}: {stage.outcome}{stage.duration !== undefined ? ` · ${stage.duration}ms` : ""}
                        </span>
                      ))}
                    </div>
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
