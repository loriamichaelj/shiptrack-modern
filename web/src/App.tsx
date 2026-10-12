import { useState } from "react";
import { Link, NavLink, Route, Routes } from "react-router";
import { ApiInspector } from "./components/ApiInspector";
import { StackBadge } from "./components/StackBadge";
import { Icon } from "./icons";
import { LivePage } from "./pages/LivePage";
import { NewShipmentPage } from "./pages/NewShipmentPage";
import { NotFoundPage } from "./pages/NotFoundPage";
import { SearchPage } from "./pages/SearchPage";
import { ShipmentDetailPage } from "./pages/ShipmentDetailPage";
import { ShipmentsPage } from "./pages/ShipmentsPage";
import { SystemPage } from "./pages/SystemPage";
import { TrackPage } from "./pages/TrackPage";
import { RuntimeProvider, useEngine, useRuntime } from "./live/runtime";
import { StackProvider } from "./stack";

/** Shown on every page while traffic is running, with a way to stop it. */
function LivePill() {
  const { engine } = useRuntime();
  const snap = useEngine();
  if (!snap.running) return null;
  return (
    <span className="live-pill">
      <span className="live-dot live-on" aria-hidden="true" /> LIVE · {snap.rate}/s
      <button type="button" className="ghost" onClick={() => { engine.stop(); }}>
        Stop
      </button>
    </span>
  );
}

export function App() {
  const [inspecting, setInspecting] = useState(false);
  return (
    <RuntimeProvider>
    <StackProvider>
      <div className="app">
        <header className="app-header">
          <Link to="/" className="brand">
            <span className="brand-mark"><Icon name="truck" size={20} /></span>
            ShipTrack
          </Link>
          <nav className="nav" aria-label="Main">
            <NavLink to="/live">Live</NavLink>
            <NavLink to="/" end>Track</NavLink>
            <NavLink to="/shipments" end>Browse</NavLink>
            <NavLink to="/shipments/new">New shipment</NavLink>
            <NavLink to="/system">System</NavLink>
          </nav>
          <LivePill />
          <button
            type="button"
            className="ghost inspector-toggle"
            aria-pressed={inspecting}
            onClick={() => { setInspecting((on) => !on); }}
          >
            <Icon name="activity" size={16} /> API activity
          </button>
        </header>
        <div className={inspecting ? "layout layout-with-inspector" : "layout"}>
          <main>
            <Routes>
              <Route path="/" element={<SearchPage />} />
              <Route path="/track/:trackingNumber" element={<TrackPage />} />
              <Route path="/live" element={<LivePage />} />
              <Route path="/shipments" element={<ShipmentsPage />} />
              <Route path="/shipments/new" element={<NewShipmentPage />} />
              <Route path="/shipments/:id" element={<ShipmentDetailPage />} />
              <Route path="/system" element={<SystemPage />} />
              <Route path="*" element={<NotFoundPage />} />
            </Routes>
          </main>
          {inspecting && <ApiInspector onClose={() => { setInspecting(false); }} />}
        </div>
        <footer className="app-footer">
          <StackBadge />
        </footer>
      </div>
    </StackProvider>
    </RuntimeProvider>
  );
}
