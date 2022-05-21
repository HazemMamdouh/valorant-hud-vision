import "@fontsource/barlow/500.css";
import "@fontsource/barlow/600.css";
import "@fontsource/barlow-condensed/600.css";
import "@fontsource/barlow-condensed/700.css";
import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import Caster from "./caster/Caster";
import "./styles.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    {new URLSearchParams(window.location.search).get("view") === "caster" ? <Caster /> : <App />}
  </React.StrictMode>,
);
