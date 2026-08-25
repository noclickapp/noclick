// Pure helpers behind the workspace file view: absolute-path → volume-relative
// resolution and the sandbox-path link matcher that turns dead /workspace/...
// anchors in agent messages into preview chips.
import { describe, it, expect } from 'vitest';
import { workspaceRelativePath } from '~/hooks/useAgentWorkspaceFiles';
import { isSandboxFilePath } from '~/components/chat/MarkdownRenderer';

describe('workspaceRelativePath', () => {
  it('strips the mount prefix', () => {
    expect(workspaceRelativePath('/workspace/seo/report.md', '/workspace')).toBe('seo/report.md');
    expect(workspaceRelativePath('/data/x.csv', '/data')).toBe('x.csv');
  });

  it('defaults the mount to /workspace when the listing has not loaded', () => {
    expect(workspaceRelativePath('/workspace/a.md', null)).toBe('a.md');
  });

  it('returns null for paths outside the mount (ephemeral sandbox disk)', () => {
    expect(workspaceRelativePath('/root/.workdir/report.md', '/workspace')).toBeNull();
    expect(workspaceRelativePath('/tmp/x', '/workspace')).toBeNull();
    // Prefix must be a path segment, not a string prefix.
    expect(workspaceRelativePath('/workspace2/a.md', '/workspace')).toBeNull();
  });
});

describe('isSandboxFilePath', () => {
  it('matches the roots agent sandboxes use', () => {
    expect(isSandboxFilePath('/workspace/seo/report.md')).toBe(true);
    expect(isSandboxFilePath('/root/.workdir/report.md')).toBe(true);
    expect(isSandboxFilePath('/tmp/out.json')).toBe(true);
    expect(isSandboxFilePath('/data/x.csv')).toBe(true);
  });

  it('never intercepts app routes or real URLs', () => {
    expect(isSandboxFilePath('/dashboard')).toBe(false);
    expect(isSandboxFilePath('/a/some-link-id')).toBe(false);
    expect(isSandboxFilePath('https://example.com/workspace/x')).toBe(false);
    expect(isSandboxFilePath('workspace/relative.md')).toBe(false);
    expect(isSandboxFilePath(undefined)).toBe(false);
  });
});
