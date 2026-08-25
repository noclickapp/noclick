// The event relay's reconnect snapshot is authoritative for work currently in
// flight. Persisted conversation history remains the fallback when the relay
// reports no active generation.

import { afterEach, expect, test } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";
import { renderChat } from "./helpers/renderChat";
import { useConversation } from "~/hooks/useConversation";
import { activeGenStore } from "~/lib/activeGenStore";

let cleanup: (() => void) | null = null;
afterEach(() => {
  cleanup?.();
  cleanup = null;
});

test("relay snapshot restores work in flight after reconnect", async () => {
  const harness = await renderChat({
    initialWorkflowId: null,
    children: <div />,
  });
  cleanup = harness.cleanup;

  expect(Object.keys(activeGenStore.gens)).toEqual([]);

  // The hook asks for committed history independently of the relay. Keep that
  // prefix empty here so the assertions isolate the restored live generation.
  harness.socket.replyTo("conversation:resume", {
    messages: [],
  });

  // A reconnect snapshot restores the relay's current generation mirror.
  await act(async () => {
    harness.socket.serverEmit("active_gen:snapshot", {
      gens: [
        {
          gen_id: "g-live",
          workflow_id: "wf-1",
          conversation_id: "conv-LIVE",
          prompt: "edit this workflow",
          started_at: Date.now() / 1000,
          text: "Working on edits…",
          events: [
            {
              type: "node_added",
              nodeId: "a",
              nodeType: "trigger-cron",
              nodeLabel: "Cron",
              status: "in_progress",
            },
          ],
          edit_steps: [],
          status: "",
        },
      ],
    });
  });

  expect(activeGenStore.gens["g-live"]).toBeDefined();
  expect(activeGenStore.byWorkflow["wf-1"]).toEqual(["g-live"]);

  const view = renderHook(() => useConversation("conv-LIVE"));

  expect(view.result.current.conversationId).toBe("conv-LIVE");
  expect(view.result.current.isStreaming).toBe(true);

  const messages = view.result.current.messages;
  expect(messages.length).toBe(2);
  expect(messages[0].text).toBe("edit this workflow");
  expect(messages[0].isUser).toBe(true);

  const lastAssistant = messages[1];
  const textSegment = (lastAssistant.editSegments || []).find(
    (segment) => segment.type === "text",
  ) as { text: string } | undefined;
  expect(textSegment?.text).toBe("Working on edits…");

  const eventsSegment = (lastAssistant.editSegments || []).find(
    (segment) => segment.type === "events",
  ) as { events: Array<{ nodeId: string }> } | undefined;
  expect(eventsSegment?.events?.length).toBe(1);
  expect(eventsSegment?.events?.[0]?.nodeId).toBe("a");
}, 15_000);

test("an empty relay snapshot falls through to persisted history", async () => {
  const harness = await renderChat({
    initialWorkflowId: null,
    children: <div />,
  });
  cleanup = harness.cleanup;

  harness.socket.replyTo("conversation:resume", {
    messages: [
      { role: "user", message: "committed prompt" },
      { role: "assistant", message: "committed reply" },
    ],
  });

  await act(async () => {
    harness.socket.serverEmit("active_gen:snapshot", { gens: [] });
  });
  expect(Object.keys(activeGenStore.gens)).toEqual([]);

  const view = renderHook(() => useConversation("conv-OLD"));

  await waitFor(
    () => {
      expect(view.result.current.conversationId).toBe("conv-OLD");
      expect(view.result.current.isStreaming).toBe(false);
      const flat = view.result.current.messages
        .map((message) => message.text || "")
        .join(" ");
      expect(flat).toContain("committed prompt");
    },
    { timeout: 5000 },
  );
}, 10_000);
