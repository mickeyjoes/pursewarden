import { StrictMode, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import "@fontsource-variable/geist";
import "@fontsource-variable/geist-mono";
import "./styles.css";
import { Moon, Sun } from "lucide-react";
import { ProvenanceBar } from "./components";
import { loadBundle, REPO_URL, type Bundle } from "./data";
import { Docs, Lab, Landing, Verify } from "./pages";

const ROUTES = { "/": "Overview", "/lab": "Attack Lab", "/verify": "Verifier", "/docs": "Reproduce" } as const;
type Route = keyof typeof ROUTES;

function useRoute(): Route {
  const get = () => (location.hash.replace(/^#/, "") || "/") as Route;
  const [r, setR] = useState<Route>(get);
  useEffect(() => {
    const on = () => { setR(get()); window.scrollTo(0, 0); };
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return r in ROUTES ? r : "/";
}

function ThemeToggle() {
  const [t, setT] = useState<string | null>(() => { try { return localStorage.getItem("pw-theme"); } catch { return null; } });
  useEffect(() => {
    if (t) document.documentElement.dataset.theme = t; else delete document.documentElement.dataset.theme;
    try { if (t) localStorage.setItem("pw-theme", t); } catch { /* storage unavailable */ }
  }, [t]);
  const dark = t ? t === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
  return (
    <button className="theme-btn" onClick={() => setT(dark ? "light" : "dark")} aria-label={`Switch to ${dark ? "light" : "dark"} theme`}>
      {dark ? <Sun size={15} /> : <Moon size={15} />}
    </button>
  );
}

function App() {
  const route = useRoute();
  const [bundle, setBundle] = useState<Bundle | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { loadBundle().then(setBundle, (e) => setErr(String(e))); }, []);
  useEffect(() => { document.title = `Pursewarden · ${ROUTES[route]}`; }, [route]);
  return (
    <>
      <a className="skip" href="#content">Skip to content</a>
      <header className="topbar">
        <div className="topbar-inner">
          <a className="brand" href="#/">
            <svg width="22" height="22" viewBox="0 0 32 32" aria-hidden><rect x="4" y="6" width="24" height="20" rx="4" fill="none" stroke="var(--accent)" strokeWidth="2.5" /><path d="M10 14h12M10 19h7" stroke="var(--allow)" strokeWidth="2.5" strokeLinecap="round" /></svg>
            Pursewarden <small>fixed-budget NEAR vaults for AI agents</small>
          </a>
          <nav className="nav" aria-label="Main">
            {(Object.keys(ROUTES) as Route[]).map((r) => (
              <a key={r} href={`#${r}`} aria-current={route === r ? "page" : undefined}>{ROUTES[r]}</a>
            ))}
          </nav>
          <ThemeToggle />
        </div>
      </header>
      <ProvenanceBar run={bundle?.runs[0] ?? null} />
      <main id="content" tabIndex={-1}>
        {err && <div className="callout bad" style={{ marginTop: 32 }}>Could not load evidence bundle: {err}</div>}
        {!bundle && !err && <p className="muted" style={{ paddingTop: 48 }}>Loading recorded evidence…</p>}
        {bundle && route === "/" && <Landing bundle={bundle} />}
        {bundle && route === "/lab" && <Lab bundle={bundle} />}
        {bundle && route === "/verify" && <Verify bundle={bundle} />}
        {bundle && route === "/docs" && <Docs bundle={bundle} />}
      </main>
      <footer>
        <div className="inner">
          <span>Built at NEAR HACKATHON 2026 · experimental, not audited</span>
          <a href={REPO_URL}>Source</a>
          <span>Pursewarden is a provisional name</span>
        </div>
      </footer>
    </>
  );
}

createRoot(document.getElementById("root")!).render(<StrictMode><App /></StrictMode>);
