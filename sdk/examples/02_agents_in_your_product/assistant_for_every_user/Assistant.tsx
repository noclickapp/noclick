/**
 * The assistant page for main.py: the signed-in user's connections, what they've spent this month,
 * the morning briefing switch, and a chat with their own agent. It gets a one-hour NoClick session
 * from main.py, so the browser never holds your API key, and talks to NoClick through the
 * TypeScript client as that one user.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import type { FormEvent } from "react";
import { Agent, Connection, NoClick, SpendCapExceeded } from "noclick";

interface ConnectionView {
  name: string;
  integration: string;
  label: string;
  reason: string;
  status: "pending" | "connected" | "disconnected";
  account: string | null;
}

interface PageData {
  session: string;
  expires_at: string;
  agent_id: string;
  briefing: boolean;
  connections: ConnectionView[];
  spent_usd: number;
  cap_usd: number;
}

interface Line {
  role: "user" | "assistant" | "error";
  text: string;
}

const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
const usd = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" });

/** The page's data from main.py, fetched again five minutes before its session expires. */
function useAssistantPage() {
  const [data, setData] = useState<PageData | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    const response = await fetch(`/api/assistant?timezone=${encodeURIComponent(timezone)}`);
    if (!response.ok) {
      setError(response.status === 401 ? "Sign in to use your assistant." : "Your assistant didn't load. Try again.");
      return;
    }
    setError(null);
    setData((await response.json()) as PageData);
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!data) return;
    const refreshIn = new Date(data.expires_at).getTime() - Date.now() - 5 * 60_000;
    const timer = setTimeout(() => void load(), Math.max(refreshIn, 0));
    return () => clearTimeout(timer);
  }, [data, load]);

  return { data, error, reload: load };
}

/**
 * A chat with the user's agent. Each message is a turn, and `wait()` returns its reply. The first
 * reply names the conversation; its key stays in localStorage, so a reload shows its `history` and
 * carries on there.
 */
function useChat(client: NoClick, agentId: string, onError: (err: unknown) => void) {
  const agent = useMemo(() => Agent.fromId(agentId, { client }), [client, agentId]);
  const storageKey = `assistant-conversation:${agentId}`;
  const [conversation, setConversation] = useState(() => localStorage.getItem(storageKey) ?? undefined);
  const [lines, setLines] = useState<Line[]>([]);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!conversation) return;
    let current = true;
    agent
      .history(conversation)
      .then((messages) => {
        if (!current) return;
        setLines(
          messages
            .filter((m) => m.role === "user" || m.role === "assistant")
            .map((m) => ({ role: m.role as Line["role"], text: m.text })),
        );
      })
      .catch((err: Error) => current && setLines([{ role: "error", text: err.message }]));
    return () => {
      current = false;
    };
  }, [agent, conversation]);

  const send = async (text: string) => {
    setLines((prev) => [...prev, { role: "user", text }]);
    setBusy(true);
    try {
      const turn = await agent.send(text, { conversation });
      const reply = await turn.wait();
      setLines((prev) => [...prev, { role: "assistant", text: reply.text }]);
      if (reply.conversation && reply.conversation !== conversation) {
        localStorage.setItem(storageKey, reply.conversation);
        setConversation(reply.conversation);
      }
    } catch (err) {
      setLines((prev) => [...prev, { role: "error", text: (err as Error).message }]);
      onError(err);
    } finally {
      setBusy(false);
    }
  };

  const startOver = () => {
    localStorage.removeItem(storageKey);
    setConversation(undefined);
    setLines([]);
  };

  return { lines, busy, send, startOver };
}

export function Assistant() {
  const { data, error, reload } = useAssistantPage();
  if (error) return <p>{error}</p>;
  if (!data) return <p>Loading your assistant…</p>;
  return <AssistantPage data={data} reload={reload} />;
}

function AssistantPage({ data, reload }: { data: PageData; reload: () => Promise<void> }) {
  const client = useMemo(() => NoClick.forSession(data.session), [data.session]);
  const [capReached, setCapReached] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const chat = useChat(client, data.agent_id, (err) => {
    if (err instanceof SpendCapExceeded && err.scope === "user") setCapReached(true);
  });

  const post = async (path: string, body?: unknown) => {
    await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    await reload();
  };

  // The user connects on NoClick's page, which sends them back here, where the page loads again.
  const connect = async (connection: ConnectionView) => {
    try {
      const link = await Connection.fromName(connection.name, { client }).connectLink({
        reason: connection.reason,
        redirectUrl: window.location.href,
      });
      window.location.assign(link.url);
    } catch (err) {
      setProblem((err as Error).message);
    }
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const text = draft.trim();
    if (!text || chat.busy) return;
    setDraft("");
    void chat.send(text);
  };

  return (
    <main className="assistant">
      <header>
        <h1>Your assistant</h1>
        <p>
          {usd.format(data.spent_usd)} of {usd.format(data.cap_usd)} used this month
        </p>
      </header>

      <section aria-label="Your accounts">
        {data.connections.map((connection) => (
          <p key={connection.name}>
            {connection.status === "connected" ? (
              <>
                {connection.label} connected{connection.account ? ` as ${connection.account}` : ""}{" "}
                <button type="button" onClick={() => void post(`/api/connections/${connection.name}/disconnect`)}>
                  Disconnect
                </button>
              </>
            ) : (
              <button type="button" onClick={() => void connect(connection)}>
                {connection.status === "disconnected" ? `Reconnect ${connection.label}` : `Connect ${connection.label}`}
              </button>
            )}
          </p>
        ))}
        {problem ? <p role="alert">{problem}</p> : null}
      </section>

      <label>
        <input
          type="checkbox"
          checked={data.briefing}
          onChange={(event) => void post("/api/assistant/briefing", { on: event.target.checked })}
        />{" "}
        Email me a briefing at 7:30 on weekdays
      </label>

      {capReached ? (
        <p role="alert">You've used this month's assistant allowance. It starts again on the 1st.</p>
      ) : null}

      <section aria-label="Assistant">
        <ol aria-live="polite">
          {chat.lines.map((line, i) => (
            <li key={i} data-role={line.role}>
              {line.text}
            </li>
          ))}
          {!chat.lines.length ? <li>Try: “What needs a reply today?” or “Put lunch with Bo on Friday at noon.”</li> : null}
          {chat.busy ? <li>Working on it…</li> : null}
        </ol>
        <form onSubmit={submit}>
          <input
            aria-label="Message"
            placeholder="Ask about your email or calendar…"
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
          />
          <button type="submit" disabled={chat.busy}>
            Send
          </button>
        </form>
        <button type="button" onClick={chat.startOver}>
          New conversation
        </button>
      </section>
    </main>
  );
}
