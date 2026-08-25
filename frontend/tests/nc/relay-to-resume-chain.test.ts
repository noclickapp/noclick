// Integrated frontend verification: an interrupted terminal frame arrives over
// the relay, the terminal handler marks the generation interrupted, and the
// banner requests a retry. The retry is intercepted so no backend run starts.
import { activeGenStore } from "~/lib/activeGenStore";
import { activeConversationStore } from "~/lib/activeConversationStore";
import { socketReceiver } from "~/lib/socket-receiver";
import { nc } from "~/lib/nc";

export default async function () {
  const byWorkflow = (activeConversationStore as any).byWorkflow || {};
  const entries = Object.entries(byWorkflow) as [string, string][];
  if (!entries.length)
    return { error: "no active conversation bound to the chat" };
  const [workflowId, conversationId] = entries[entries.length - 1];

  let firedPrompt: string | null = null;
  const intercept = (event: Event) => {
    firedPrompt = (event as CustomEvent).detail?.prompt ?? null;
    event.stopImmediatePropagation();
  };
  document.addEventListener("noclick:builder:retry", intercept, true);

  const genId = `relay_to_resume_${Date.now()}`;
  try {
    activeGenStore.gens[genId] = {
      gen_id: genId,
      workflow_id: workflowId,
      conversation_id: conversationId,
      prompt: "Build the thing",
      started_at: Date.now() / 1000,
      text: "",
      events: [],
      edit_steps: [],
      status: "Modifying workflow",
      lastEventAt: Date.now(),
    } as any;
    (activeGenStore.byConversation[conversationId] ||= []).push(genId);
    (activeGenStore.byWorkflow[workflowId] ||= []).push(genId);

    (socketReceiver as any).handleEvent("active_gen:terminal", [
      {
        gen_id: genId,
        conversation_id: conversationId,
        workflow_id: workflowId,
        outcome: "interrupted",
      },
    ]);
    const markedInterrupted = !!activeGenStore.gens[genId]?.interrupted;

    await nc.wait.ms(800);

    return {
      markedInterrupted,
      autoResumeFired: firedPrompt === "Build the thing",
      note: "autoResumeFired can be false after the per-conversation retry cap is reached",
    };
  } finally {
    document.removeEventListener("noclick:builder:retry", intercept, true);
    const currentWindow = window as any;
    if (currentWindow.__ncBannerDemo?.cleanup)
      currentWindow.__ncBannerDemo.cleanup();
    delete activeGenStore.gens[genId];
    activeGenStore.byConversation[conversationId] = (
      activeGenStore.byConversation[conversationId] || []
    ).filter((id) => id !== genId);
    activeGenStore.byWorkflow[workflowId] = (
      activeGenStore.byWorkflow[workflowId] || []
    ).filter((id) => id !== genId);
  }
}
