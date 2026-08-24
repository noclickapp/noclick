// This source-level regression prevents the dangerous sandbox-token pair from
// returning through a refactor or copied iframe. Runtime browser coverage lives
// beside it, but this check fails quickly even when Chromium is unavailable.

import { readdirSync, readFileSync } from 'node:fs';
import { relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import {
  EDITOR_COMPONENT_SANDBOX,
  READ_ONLY_COMPONENT_SANDBOX,
} from '~/lib/componentSandbox';

const rendererSource = readFileSync(
  new URL('../../app/components/interface/blocks/HtmlReactBlock.tsx', import.meta.url),
  'utf8',
);
const appRoot = fileURLToPath(new URL('../../app/', import.meta.url));

function sourceFiles(directory: string): string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = resolve(directory, entry.name);
    if (entry.isDirectory()) return sourceFiles(path);
    return /\.[cm]?[jt]sx?$/.test(entry.name) ? [path] : [];
  });
}

describe('custom component sandbox policy', () => {
  it('never grants author srcdoc a same-origin capability', () => {
    expect(READ_ONLY_COMPONENT_SANDBOX.split(/\s+/)).not.toContain('allow-same-origin');
    expect(EDITOR_COMPONENT_SANDBOX.split(/\s+/)).not.toContain('allow-same-origin');
    expect(rendererSource).not.toContain('allow-same-origin');
    expect(
      sourceFiles(appRoot)
        .filter((path) => readFileSync(path, 'utf8').includes('allow-same-origin'))
        .map((path) => relative(appRoot, path)),
    ).toEqual([]);
  });

  it('keeps public/read-only documents at the minimum script-only sandbox', () => {
    expect(READ_ONLY_COMPONENT_SANDBOX).toBe('allow-scripts');
    expect(rendererSource).toContain('sandbox={componentSandbox(readOnly)}');
  });
});
