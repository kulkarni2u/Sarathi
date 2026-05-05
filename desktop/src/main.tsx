import "./theme.css";
import React from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import "@radix-ui/themes/styles.css";
import "./styles.css";

createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
