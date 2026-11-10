import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
// DESIGN.md's faces, self-hosted (OFL, no font CDN: the demo works offline). Source Serif 4 stands in for Signifier
// (with its optical sizes, roman and italic), Inter for Söhne (variable, so the half-step weights 430/450/480 exist).
import "@fontsource-variable/source-serif-4/opsz.css";
import "@fontsource-variable/source-serif-4/opsz-italic.css";
import "@fontsource-variable/inter/index.css";
import { detectLang } from "./i18n";
import { Root } from "./Root";
import "./styles.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <Root initialLang={detectLang()} />
  </StrictMode>,
);
