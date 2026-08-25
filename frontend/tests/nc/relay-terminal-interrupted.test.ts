// Verifies the frontend liveness handler: an interrupted terminal signal keeps
// the generation available for automatic resume, while normal completion
// evicts it.
import { activeGenStore } from "~/lib/activeGenStore";
import { socketReceiver } from "~/lib/socket-receiver";
import { nc } from "~/lib/nc";

function seedGen(genId: string) {
  activeGenStore.gens[genId] = {
    gen_id: genId,
    workflow_id: "wf",
    conversation_id: "cv",
    prompt: "p",
    started_at: Date.now() / 1000,
    text: "",
    events: [],
    edit_steps: [],
    status: "Modifying workflow",
    lastEventAt: Date.now(),
  } as any;
}

export default async function () {
  const interruptedId = `relay_term_interrupted_${Date.now()}`;
  const completeId = `relay_term_complete_${Date.now()}`;
  try {
    seedGen(interruptedId);
    (socketReceiver as any).handleEvent("active_gen:terminal", [
      {
        gen_id: interruptedId,
        conversation_id: "cv",
        workflow_id: "wf",
        outcome: "interrupted",
      },
    ]);
    const interruptedGen = activeGenStore.gens[interruptedId];
    nc.assert.truthy(
      interruptedGen,
      "interrupted gen must stay in the store so it can resume",
    );
    nc.assert.truthy(
      interruptedGen?.interrupted,
      "gen must be flagged interrupted",
    );

    seedGen(completeId);
    (socketReceiver as any).handleEvent("active_gen:terminal", [
      {
        gen_id: completeId,
        conversation_id: "cv",
        workflow_id: "wf",
        outcome: "complete",
      },
    ]);
    nc.assert.falsy(
      activeGenStore.gens[completeId],
      "a completed run still evicts",
    );

    return {
      interruptedKeptAndFlagged: !!interruptedGen?.interrupted,
      completeEvicted: !activeGenStore.gens[completeId],
    };
  } finally {
    delete activeGenStore.gens[interruptedId];
    delete activeGenStore.gens[completeId];
  }
}
