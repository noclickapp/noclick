// @vitest-environment jsdom
// Covers the deleteFile path added to useAgentWorkspaceFiles: it sends
// agent_workspace:delete with the file path and optimistically drops the row,
// and surfaces a server rejection to the caller.

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, act, waitFor } from '@testing-library/react';

const { sendEventAsync } = vi.hoisted(() => ({ sendEventAsync: vi.fn() }));
vi.mock('~/lib/socket-sender', () => ({ sendEventAsync }));

import { useAgentWorkspaceFiles, type WorkspaceFile } from '~/hooks/useAgentWorkspaceFiles';

const file = (path: string): WorkspaceFile => ({ path, size: 1, mtime: 0, url_path: `/f?${path}` });

interface WsPayload {
  event_name?: string;
  path?: string;
}

beforeEach(() => sendEventAsync.mockClear());

describe('useAgentWorkspaceFiles.deleteFile', () => {
  it('sends agent_workspace:delete and drops the row', async () => {
    let files = [file('a.md'), file('b.md')];
    sendEventAsync.mockImplementation(async (...args: unknown[]) => {
      const p = args[0] as WsPayload | undefined;
      if (p?.event_name === 'agent_workspace:list') {
        return { success: true, workspace: '/workspace', exists: true, truncated: false, files, upload_url_path: '/u' };
      }
      if (p?.event_name === 'agent_workspace:delete') {
        files = files.filter(f => f.path !== p.path);
        return { success: true, path: p.path };
      }
      return { success: false };
    });

    const { result } = renderHook(() => useAgentWorkspaceFiles('wf', 'node1', 'ck1', 0));
    await act(async () => { await result.current.refresh(); });
    expect(result.current.files.map(f => f.path)).toEqual(['a.md', 'b.md']);

    await act(async () => { await result.current.deleteFile('a.md'); });

    const deleteCall = sendEventAsync.mock.calls.find(
      c => (c[0] as WsPayload).event_name === 'agent_workspace:delete',
    );
    expect(deleteCall?.[0]).toMatchObject({
      event_name: 'agent_workspace:delete',
      workflow_id: 'wf', node_id: 'node1', conversation_key: 'ck1', path: 'a.md',
    });
    await waitFor(() => expect(result.current.files.map(f => f.path)).toEqual(['b.md']));
  });

  it('rejects when the server denies the delete', async () => {
    sendEventAsync.mockImplementation(async (...args: unknown[]) => {
      const p = args[0] as WsPayload | undefined;
      if (p?.event_name === 'agent_workspace:list') {
        return { success: true, workspace: '/workspace', exists: true, truncated: false, files: [file('a.md')], upload_url_path: '/u' };
      }
      return { success: false, error: 'Access denied' };
    });

    const { result } = renderHook(() => useAgentWorkspaceFiles('wf', 'node1', 'ck1', 0));
    await act(async () => { await result.current.refresh(); });
    await act(async () => {
      await expect(result.current.deleteFile('a.md')).rejects.toThrow('Access denied');
    });
    // Rejection means no optimistic drop — the row stays.
    expect(result.current.files.map(f => f.path)).toEqual(['a.md']);
  });
});
