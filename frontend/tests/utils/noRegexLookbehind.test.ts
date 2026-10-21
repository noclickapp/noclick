// Safari before 16.4 has no regex lookbehind, and the production build turns a lookbehind literal into
// `new RegExp(...)`, so it throws at render time there and the root ErrorBoundary takes the page (the coordinator
// chat on iOS 15, 2026-10-21). Dependencies are guarded separately (MarkdownRenderer.safari.test.tsx).

import { readdirSync, readFileSync } from 'node:fs';
import { join, relative } from 'node:path';
import { describe, it, expect } from 'vitest';

const APP = join(__dirname, '../../app');
const LOOKBEHIND = /\(\?<[=!]/;

function sources(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap(entry => {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) return sources(path);
    return /\.tsx?$/.test(entry.name) && !/\.test\.tsx?$/.test(entry.name) ? [path] : [];
  });
}

describe('app source on Safari < 16.4', () => {
  it('has no regex lookbehind', () => {
    const offenders = sources(APP).flatMap(file =>
      readFileSync(file, 'utf8')
        .split('\n')
        .flatMap((line, i) => (LOOKBEHIND.test(line) ? [`${relative(APP, file)}:${i + 1}`] : [])),
    );
    expect(offenders).toEqual([]);
  });
});
