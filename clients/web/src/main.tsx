import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { OrchestrateDemo } from "./dev/OrchestrateDemo";
import "./theme.css";

// ``?demo=team`` opens a UI sandbox with hardcoded orchestrate
// scenarios so we can iterate on the visual without spinning up a
// real broadcast in PyCharm. Anything else loads the real app.
const params = new URLSearchParams(window.location.search);
const demo = params.get("demo");

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    {demo === "team" ? <OrchestrateDemo /> : <App />}
  </StrictMode>,
);
