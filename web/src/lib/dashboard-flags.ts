declare global {
  interface Window {
    /** Set true by the server only for `elidia dashboard --tui` (or ELIDIA_DASHBOARD_TUI=1). */
    __ELIDIA_DASHBOARD_EMBEDDED_CHAT__?: boolean;
    /** @deprecated Older injected name; treated as on when true. */
    __ELIDIA_DASHBOARD_TUI__?: boolean;
  }
}

/** True only when the dashboard was started with embedded TUI Chat (`elidia dashboard --tui`). */
export function isDashboardEmbeddedChatEnabled(): boolean {
  if (typeof window === "undefined") return false;
  if (window.__ELIDIA_DASHBOARD_EMBEDDED_CHAT__ === true) return true;
  return window.__ELIDIA_DASHBOARD_TUI__ === true;
}
