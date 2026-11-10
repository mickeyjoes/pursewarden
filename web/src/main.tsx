import { StrictMode, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import "@fontsource-variable/geist";
import "@fontsource-variable/geist-mono";
import "./styles.css";
import { Moon, Sun } from "lucide-react";
import { ProvenanceBar, provOf } from "./components";
import { loadBundle, REPO_URL, type Bundle } from "./data";
import { Burst, Docs, Lab, Landing, Verify } from "./pages";
import { Testnet } from "./testnet";
import { Tour } from "./tour";

const ROUTES = { "/": "Overview", "/tour": "Tour", "/lab": "Attack Lab", "/burst": "Burst (G2)", "/verify": "Verifier", "/testnet": "Testnet", "/docs": "Reproduce" } as const;
type Route = keyof typeof ROUTES;

function useRoute(): [Route, number] {
  const get = (): [Route, number] => {
    const h = location.hash.replace(/^#/, "") || "/";
    const m = h.match(/^\/tour(?:\/(\d+))?$/);
    if (m) return ["/tour", Number(m[1] ?? 1)];
    return [(h in ROUTES ? h : "/") as Route, 0];
  };
  const [r, setR] = useState<[Route, number]>(get);
  useEffect(() => {
    const on = () => { setR(get()); window.scrollTo(0, 0); };
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return r;
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
  const [route, step] = useRoute();
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
            {(Object.keys(ROUTES) as Route[]).filter((r) => r !== "/tour").map((r) => (
              <a key={r} href={`#${r}`} aria-current={route === r ? "page" : undefined}>{ROUTES[r]}</a>
            ))}
          </nav>
          <ThemeToggle />
        </div>
      </header>
      <ProvenanceBar info={!bundle ? null : route === "/testnet" && bundle.testnet_runs?.[0]
        ? { run_id: bundle.testnet_runs[0].run_id, chain_id: bundle.testnet_runs[0].node.chain_id, version: bundle.testnet_runs[0].node.version,
            note: `inspected at final block #${bundle.testnet_runs[0].cut.q_height}`, network: "TESTNET" }
        : (route === "/burst" || (route === "/tour" && step <= 2)) && bundle.g2_runs?.[0]
        ? { run_id: bundle.g2_runs[0].run_id, chain_id: bundle.g2_runs[0].node.chain_id, version: "2.13.4",
            digest: bundle.g2_runs[0].protected.replay_capture_sha256, digestTitle: "SHA-256 of the protected-vault capture rebuilt by replay" }
        : provOf(bundle.runs[0])} />
      <main id="content" tabIndex={-1}>
        {err && <div className="callout bad" style={{ marginTop: 32 }}>Could not load evidence bundle: {err}</div>}
        {!bundle && !err && <p className="muted" style={{ paddingTop: 48 }}>Loading recorded evidence…</p>}
        {bundle && route === "/" && <Landing bundle={bundle} />}
        {bundle && route === "/tour" && <Tour bundle={bundle} step={step} />}
        {bundle && route === "/lab" && <Lab bundle={bundle} />}
        {bundle && route === "/burst" && <Burst bundle={bundle} />}
        {bundle && route === "/verify" && <Verify bundle={bundle} />}
        {bundle && route === "/testnet" && <Testnet bundle={bundle} />}
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
