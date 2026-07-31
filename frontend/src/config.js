// Centralized host configuration for API and WebSocket connections

// Allow overriding via environment variables (Vite prefix VITE_ is required)
export const API_BASE = import.meta.env.VITE_API_BASE || "";

const getWebSocketBase = () => {
  if (import.meta.env.VITE_WS_BASE) {
    return import.meta.env.VITE_WS_BASE;
  }
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}`;
};

export const WS_BASE = getWebSocketBase();
