import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { OrchestrateDemo } from "./dev/OrchestrateDemo";
import { PlanModeDemo } from "./dev/PlanModeDemo";
import "./theme.css";

// Demo URLs:
//   ?demo=team   — orchestrate / team-progress UI sandbox
//   ?demo=plan   — plan-mode (row 50) UI sandbox: badge, info
//                  banner, PlanCard pending / approved / dismissed
// Anything else loads the real app.
const params = new URLSearchParams(window.location.search);
const demo = params.get("demo");

function pickRoot() {
  if (demo === "team") return <OrchestrateDemo />;
  if (demo === "plan") return <PlanModeDemo />;
  return <App />;
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>{pickRoot()}</StrictMode>,
);
