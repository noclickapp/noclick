// Unit tests for agentOutputMedia — the shared extractor that pulls generated
// image/video URLs out of an AI Agent node's raw output dict (used by the
// inline node output panel and the Run results dialog).

import { describe, it, expect } from 'vitest';
import { agentOutputMedia } from '~/lib/agentOutputMedia';

describe('agentOutputMedia', () => {
  it('extracts image URLs from {images:[{url}]}', () => {
    expect(agentOutputMedia({ images: [{ url: 'https://r2/a.png' }, { url: 'https://r2/b.png' }] })).toEqual({
      images: ['https://r2/a.png', 'https://r2/b.png'],
      videos: [],
    });
  });

  it('extracts video URLs from {videos:[{url}]}', () => {
    expect(agentOutputMedia({ videos: [{ url: 'https://r2/v.mp4' }] })).toEqual({
      images: [],
      videos: ['https://r2/v.mp4'],
    });
  });

  it('handles plain string entries and skips malformed ones', () => {
    expect(
      agentOutputMedia({ images: ['https://r2/s.png', { url: 'https://r2/o.png' }, { nope: 1 }, null, ''] }),
    ).toEqual({ images: ['https://r2/s.png', 'https://r2/o.png'], videos: [] });
  });

  it('returns empty lists for non-object / missing / text-only output', () => {
    expect(agentOutputMedia(null)).toEqual({ images: [], videos: [] });
    expect(agentOutputMedia('hi')).toEqual({ images: [], videos: [] });
    expect(agentOutputMedia({ type: 'agent', response: 'just text' })).toEqual({ images: [], videos: [] });
  });
});
