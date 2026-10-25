import { useEffect, useRef } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { Settings2, X } from "lucide-react";
import { subscribe } from "./lib/socket";
import { api } from "./lib/api";
import { prefs } from "./lib/prefs";
import type { SessionSummary } from "./lib/types";
import { useUi } from "./stores/ui";
import Sidebar from "./components/Sidebar";
import StatusIndicator from "./components/StatusIndicator";
import { CENTER } from "./components/Panel";
import Home from "./components/Home";
import SessionView from "./components/SessionView";
import RunView from "./components/RunView";
import ExportsView from "./components/ExportsView";
import WorkspaceView from "./components/WorkspaceView";
import ModelsView from "./components/ModelsView";
import GuideView from "./components/GuideView";

export default function App() {
  const { view, tab, setTab, setView, close, addEvent, setRunning, setError } = useUi();
  const sessions = useQuery({ queryKey: ["sessions"], queryFn: () => api.get<SessionSummary[]>("/api/sessions") });
  const startupRestored = useRef(false);

  useEffect(() => {
    if (startupRestored.current || !sessions.data) return;
    startupRestored.current = true;
    if (view.kind !== "home" || tab !== "research") return;
    // Back to the view the last session ended on, when it still exists.
    const last = prefs().last_view;
    if (last?.kind === "session" && sessions.data.some((s) => s.id === last.id)) setView(last);
    else if (last?.kind === "run") {
      api.get(`/api/runs/${encodeURIComponent(last.name)}`).then(
        () => setView(last),
        () => sessions.data[0] && setView({ kind: "session", id: sessions.data[0].id }),
      );
    } else if (last?.kind === "exports" || last?.kind === "home") setView(last);
    else if (sessions.data[0]) setView({ kind: "session", id: sessions.data[0].id });
  }, [sessions.data, view.kind, tab, setView]);

  // Esc closes the Workspace and Models panels, unless a modal or a field has focus.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      const typing = target && (target.tagName === "TEXTAREA" || target.tagName === "INPUT" || target.tagName === "SELECT");
      if (e.key === "Escape" && !typing && (view.kind === "workspace" || view.kind === "models") && !document.querySelector(".fixed.inset-0")) close();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [view.kind, close]);
  const client = useQueryClient();

  useEffect(
    () =>
      subscribe((msg) => {
        if (msg.type === "event") {
          addEvent(msg.session, msg.event);
          if (msg.event.type === "permission_request" || msg.event.type === "permission_answer") {
            void client.invalidateQueries({ queryKey: ["session", msg.session] });
          }
          if (msg.event.type === "done" || msg.event.type === "handoff") {
            void client.invalidateQueries({ queryKey: ["session", msg.session] });
            void client.invalidateQueries({ queryKey: ["sessions"] });
            void client.invalidateQueries({ queryKey: ["activity", msg.session] });
          }
        } else if (msg.type === "state" && msg.session) {
          setRunning(msg.session, msg.running);
          void client.invalidateQueries({ queryKey: ["health"] });
          void client.invalidateQueries({ queryKey: ["sessions"] });
          if (!msg.running) void client.invalidateQueries({ queryKey: ["runs"] });
        } else if (msg.type === "state") {
          // The socket has reopened. Refresh mounted sessions so requests missed while
          // disconnected appear with their current running state and decision controls.
          void client.invalidateQueries({ queryKey: ["session"] });
          void client.invalidateQueries({ queryKey: ["activity"] });
        } else if (msg.type === "error") {
          setError(msg.session, msg.text);
        }
      }),
    [addEvent, setRunning, setError, client],
  );

  return (
    <div className="relative flex h-full">
      <Sidebar />
      <main className={`flex flex-col ${CENTER}`}>
        <header className="flex h-11 shrink-0 items-center gap-1 border-b border-border px-4">
          {(["research", "guide"] as const).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={clsx(
                "rounded-md px-3 py-1 text-[0.8125rem]",
                tab === t ? "bg-panel font-medium text-fg" : "text-muted hover:text-fg",
              )}
            >
              {t === "research" ? "Research" : "Guide"}
            </button>
          ))}
          <div className="flex-1" />
          {(view.kind === "workspace" || view.kind === "models") && tab === "research" && (
            <button onClick={close} title="Close (Esc)" className="flex items-center gap-1 rounded-md px-2.5 py-1 text-[0.8125rem] text-muted hover:bg-panel hover:text-fg">
              <X size="0.875rem" /> Close
            </button>
          )}
          <StatusIndicator />
          <button
            onClick={() => (view.kind === "models" && tab === "research" ? close() : setView({ kind: "models" }))}
            title="Models: connections, sign-in and settings"
            className={clsx(
              "flex items-center gap-1.5 rounded-md px-3 py-1 text-[0.8125rem]",
              view.kind === "models" && tab === "research" ? "bg-panel font-medium text-fg" : "text-muted hover:text-fg",
            )}
          >
            <Settings2 size="0.875rem" /> Models
          </button>
        </header>
        <div className="min-h-0 flex-1">
          {tab === "guide" ? (
            <GuideView />
          ) : view.kind === "session" ? (
            <SessionView key={view.id} id={view.id} />
          ) : view.kind === "run" ? (
            <RunView key={view.name} name={view.name} file={view.file} />
          ) : view.kind === "exports" ? (
            <ExportsView />
          ) : view.kind === "workspace" ? (
            <WorkspaceView initialPath={view.path} />
          ) : view.kind === "models" ? (
            <ModelsView />
          ) : (
            <Home />
          )}
        </div>
      </main>
    </div>
  );
}
