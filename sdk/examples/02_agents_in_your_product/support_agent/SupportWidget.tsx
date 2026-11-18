/**
 * The support chat for Northwind's site: a Help button in the corner that opens a chat with the
 * support agent from main.py, as the signed-in customer. It asks main.py for a session only when
 * opened, so the browser holds a one-hour token for this one customer and never your API key.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { FormEvent } from "react";
import { Agent, NoClick } from "noclick";

interface SupportSession {
  session: string;
  expires_at: string;
  user_id: string;
  agent_id: string;
  email: string;
  phone: string;
}

interface Line {
  role: "user" | "assistant" | "person" | "error";
  text: string;
}

/** A session from main.py once the widget is open, fetched again five minutes before it expires. */
function useSupportSession(open: boolean) {
  const [session, setSession] = useState<SupportSession | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    const response = await fetch("/api/support/session");
    if (!response.ok) {
      setError(response.status === 401 ? "Sign in to chat with us about your orders." : "Support didn't load. Try again.");
      return;
    }
    setError(null);
    setSession((await response.json()) as SupportSession);
  }, []);

  useEffect(() => {
    if (open && !session) void load();
  }, [open, session, load]);

  useEffect(() => {
    if (!session) return;
    const refreshIn = new Date(session.expires_at).getTime() - Date.now() - 5 * 60_000;
    const timer = setTimeout(() => void load(), Math.max(refreshIn, 0));
    return () => clearTimeout(timer);
  }, [session, load]);

  return { session, error };
}

const shown = (role: string | null): role is Line["role"] => role === "user" || role === "assistant" || role === "person";

/**
 * The customer's conversation with the support agent. Each message is a turn, and `wait()` returns
 * its reply; the conversation's key stays in localStorage, so a reload continues it. `watch` follows
 * the conversation for what this chat didn't send: the agent's turn once your team answers a refund,
 * and your team's own replies (`person`) after a hand-off. Turns this chat sent come through there
 * too, so it skips those by their operation id.
 */
function useSupportChat(session: SupportSession) {
  const client = useMemo(() => NoClick.forSession(session.session), [session.session]);
  const agent = useMemo(() => Agent.fromId(session.agent_id, { client }), [client, session.agent_id]);
  const storageKey = `support-conversation:${session.user_id}`;
  const [conversation, setConversation] = useState(() => localStorage.getItem(storageKey) ?? undefined);
  const [lines, setLines] = useState<Line[]>([]);
  const [busy, setBusy] = useState(false);
  const sent = useRef(new Set<string>());

  useEffect(() => {
    if (!conversation) return;
    const controller = new AbortController();
    (async () => {
      const messages = await agent.history(conversation);
      if (controller.signal.aborted) return;
      setLines(messages.filter((m) => shown(m.role)).map((m) => ({ role: m.role as Line["role"], text: m.text })));
      for await (const event of agent.watch(conversation, { signal: controller.signal })) {
        if (event.type !== "message" || !shown(event.role) || !event.text) continue;
        if (event.operationId && sent.current.has(event.operationId)) continue;
        const line = { role: event.role, text: event.text };
        setLines((prev) => [...prev, line]);
      }
    })().catch((err: Error) => {
      if (!controller.signal.aborted) setLines((prev) => [...prev, { role: "error", text: err.message }]);
    });
    return () => controller.abort();
  }, [agent, conversation]);

  const send = async (text: string) => {
    setLines((prev) => [...prev, { role: "user", text }]);
    setBusy(true);
    try {
      const turn = await agent.send(text, { conversation });
      sent.current.add(turn.id);
      const reply = await turn.wait();
      setLines((prev) => [...prev, { role: "assistant", text: reply.text }]);
      if (reply.conversation && reply.conversation !== conversation) {
        localStorage.setItem(storageKey, reply.conversation);
        setConversation(reply.conversation);
      }
    } catch (err) {
      setLines((prev) => [...prev, { role: "error", text: (err as Error).message }]);
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

function SupportChat({ session }: { session: SupportSession }) {
  const chat = useSupportChat(session);
  const [draft, setDraft] = useState("");

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const text = draft.trim();
    if (!text || chat.busy) return;
    setDraft("");
    void chat.send(text);
  };

  return (
    <section aria-label="Northwind support">
      <ol aria-live="polite">
        {chat.lines.map((line, i) => (
          <li key={i} data-role={line.role}>
            {line.text}
          </li>
        ))}
        {!chat.lines.length ? <li>Hi! Ask about an order, a refund, shipping or your subscription.</li> : null}
        {chat.busy ? <li>Typing…</li> : null}
      </ol>
      <form onSubmit={submit}>
        <input
          aria-label="Message"
          placeholder="Ask about an order, shipping or your subscription…"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
        />
        <button type="submit" disabled={chat.busy}>
          Send
        </button>
      </form>
      <button type="button" onClick={chat.startOver}>
        Start over
      </button>
      <p>
        Or email <a href={`mailto:${session.email}`}>{session.email}</a>, or call{" "}
        <a href={`tel:${session.phone}`}>{session.phone}</a>.
      </p>
    </section>
  );
}

export function SupportWidget() {
  const [open, setOpen] = useState(false);
  const { session, error } = useSupportSession(open);

  return (
    <div style={{ position: "fixed", right: 16, bottom: 16, zIndex: 1000, width: open ? "min(380px, calc(100vw - 32px))" : "auto" }}>
      {open ? (
        <div className="support-panel">
          <button type="button" onClick={() => setOpen(false)} aria-label="Close support">
            ×
          </button>
          {error ? <p>{error}</p> : null}
          {session ? <SupportChat session={session} /> : error ? null : <p>Connecting you to support…</p>}
        </div>
      ) : (
        <button type="button" onClick={() => setOpen(true)}>
          Help
        </button>
      )}
    </div>
  );
}
