import { useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import { send } from "../lib/socket";
import type { SessionDetail } from "../lib/types";
import { useUi } from "../stores/ui";
import PromptBar, { type Attached, useSettings } from "./PromptBar";

export async function attachNote(sid: string, files: Attached[]): Promise<string> {
  if (!files.length) return "";
  const res = await api.post<{ note: string }>(`/api/sessions/${sid}/attach`, { files });
  return `\n\n${res.note}`;
}

export default function Home() {
  const { setView, nextConnection, setNextConnection, setError } = useUi();
  const settings = useSettings();
  const client = useQueryClient();
  const connection = nextConnection["new"] ?? settings.data?.default_connection ?? "claude-sub";

  const start = async (text: string, files: Attached[]) => {
    try {
      const session = await api.post<SessionDetail>("/api/sessions", {});
      const note = await attachNote(session.id, files);
      setNextConnection(session.id, connection);
      setView({ kind: "session", id: session.id });
      send({ type: "send", session: session.id, text: text + note, connection });
      void client.invalidateQueries({ queryKey: ["sessions"] });
    } catch (e) {
      setError("new", (e as Error).message);
    }
  };

  return (
    <div className="flex h-full flex-col items-center justify-center px-6 pb-24">
      <h1 className="mb-6 text-[1.625rem] font-medium tracking-tight text-fg">What do you want to find out?</h1>
      <div className="w-full max-w-2xl">
        <PromptBar onSend={start} connection={connection} onConnection={(c) => setNextConnection("new", c)} autoFocus />
      </div>
    </div>
  );
}
