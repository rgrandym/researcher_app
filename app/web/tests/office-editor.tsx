import React, { useState } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import OfficePane from "../src/components/OfficePane";
import "../src/index.css";

const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
function TestEditor() {
  const [slug, setSlug] = useState("book");
  return <><nav>{["book", "deck"].map((name) => <button key={name} onClick={() => setSlug(name)}>Open {name}</button>)}</nav>
    <OfficePane key={slug} run="office-test" subject={{ slug, path: `${slug}.${slug === "book" ? "xlsx" : "pptx"}`, format: slug === "book" ? "xlsx" : "pptx", master: `${slug}.md`, role: "subject", editable: true, extracted: true, counts: {}, deliverable: null }} edit onReady={() => undefined} />
  </>;
}
createRoot(document.getElementById("root")!).render(<React.StrictMode><QueryClientProvider client={client}><TestEditor /></QueryClientProvider></React.StrictMode>);
