import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import path from "path";

const BACKEND = process.env.ELIDIA_DASHBOARD_URL ?? "http://127.0.0.1:9119";

/**
 * In production the Python `elidia dashboard` server injects a one-shot
 * session token into `index.html` (see `elidia_cli/web_server.py`). The
 * Vite dev server serves its own `index.html`, so unless we forward that
 * token, every protected `/api/*` call 401s.
 *
 * This plugin fetches the running dashboard's `index.html` on each dev page
 * load, scrapes the `window.__ELIDIA_SESSION_TOKEN__` assignment, and
 * re-injects it into the dev HTML. No-op in production builds.
 */
function elidiaDevToken(): Plugin {
  const TOKEN_RE = /window\.__ELIDIA_SESSION_TOKEN__\s*=\s*"([^"]+)"/;
  const EMBEDDED_RE =
    /window\.__ELIDIA_DASHBOARD_EMBEDDED_CHAT__\s*=\s*(true|false)/;
  const LEGACY_TUI_RE =
    /window\.__ELIDIA_DASHBOARD_TUI__\s*=\s*(true|false)/;

  return {
    name: "elidia:dev-session-token",
    apply: "serve",
    async transformIndexHtml() {
      try {
        const res = await fetch(BACKEND, { headers: { accept: "text/html" } });
        const html = await res.text();
        const match = html.match(TOKEN_RE);
        if (!match) {
          console.warn(
            `[elidia] Could not find session token in ${BACKEND} — ` +
              `is \`elidia dashboard\` running? /api calls will 401.`,
          );
          return;
        }
        const embeddedMatch = html.match(EMBEDDED_RE);
        const legacyMatch = html.match(LEGACY_TUI_RE);
        const embeddedJs = embeddedMatch
          ? embeddedMatch[1]
          : legacyMatch
            ? legacyMatch[1]
            : "false";
        return [
          {
            tag: "script",
            injectTo: "head",
            children:
              `window.__ELIDIA_SESSION_TOKEN__="${match[1]}";` +
              `window.__ELIDIA_DASHBOARD_EMBEDDED_CHAT__=${embeddedJs};`,
          },
        ];
      } catch (err) {
        console.warn(
          `[elidia] Dashboard at ${BACKEND} unreachable — ` +
            `start it with \`elidia dashboard\` or set ELIDIA_DASHBOARD_URL. ` +
            `(${(err as Error).message})`,
        );
      }
    },
  };
}

export default defineConfig({
  plugins: [react(), tailwindcss(), elidiaDevToken()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
    // When @aiutils/ui is symlinked via `file:../../design-language`,
    // Node's module resolution would pick up shared deps from
    // design-language/node_modules/*, giving us two copies + breaking
    // hooks (useRef-of-null), webgl contexts, etc. Force everything that
    // exists in BOTH places to use the dashboard's copy.
    //
    // Don't list packages here that only exist in the DS (nanostores,
    // @nanostores/react) — Vite dedupe errors out when it can't find
    // them at the project root.
    dedupe: [
      "react",
      "react-dom",
      "@react-three/fiber",
      "@observablehq/plot",
      "three",
      "leva",
      "gsap",
    ],
  },
  build: {
    outDir: "../elidia_cli/web_dist",
    emptyOutDir: true,
  },
  server: {
    proxy: {
      "/api": {
        target: BACKEND,
        ws: true,
      },
      // Same host as `elidia dashboard` must serve these; Vite has no
      // dashboard-plugins/* files, so without this, plugin scripts 404
      // or receive index.html in dev.
      "/dashboard-plugins": BACKEND,
    },
  },
});
