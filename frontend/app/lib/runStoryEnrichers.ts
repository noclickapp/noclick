// What the hosted run popup shows beyond the stored snapshot (mirrors backend/cloud/bootstrap.py: the engine owns
// the seam and a working default, cloud registers implementations). Apart from runResults, which reads runs over
// the socket, so the hosted bootstrap registers here on every page for nothing.
import type { RunSnapshot, RunStoryExtras } from '~/lib/runResults';

export type RunStoryEnricher = (workflowId: string, snapshot: RunSnapshot) => Promise<RunStoryExtras>;

export const runStoryEnrichers: RunStoryEnricher[] = [];

export function registerRunStoryEnricher(enricher: RunStoryEnricher): void {
    runStoryEnrichers.push(enricher);
}
