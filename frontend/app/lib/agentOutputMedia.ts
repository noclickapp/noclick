// Extracts generated image/video URLs from an AI Agent node's raw output dict.
// image/video/kling models return `{ images: [{url}], videos: [{url}] }`; this
// is the single extractor shared by every surface that displays a run's media
// output (the inline node output panel and the Run results dialog) so they
// render generated media the same way the chat interface does.

export interface AgentOutputMedia {
  images: string[];
  videos: string[];
}

function urlsFromList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  const out: string[] = [];
  for (const item of value) {
    const url =
      typeof item === 'string'
        ? item
        : item && typeof item === 'object'
          ? (item as Record<string, unknown>).url
          : null;
    if (typeof url === 'string' && url) out.push(url);
  }
  return out;
}

export function agentOutputMedia(output: unknown): AgentOutputMedia {
  if (!output || typeof output !== 'object') return { images: [], videos: [] };
  const o = output as Record<string, unknown>;
  return { images: urlsFromList(o.images), videos: urlsFromList(o.videos) };
}
