// @vitest-environment jsdom

import { renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const sendEventAsync = vi.fn();

vi.mock('~/lib/socket-sender', () => ({
  sendEventAsync: (...args: unknown[]) => sendEventAsync(...args),
}));

import { useRenewableResourceUrl } from '~/hooks/useRenewableResourceUrl';

const RESOURCE_ID = '12345678-1234-1234-1234-1234567890ab';

describe('useRenewableResourceUrl', () => {
  beforeEach(() => {
    sendEventAsync.mockReset();
  });

  it('leaves ordinary URLs alone', () => {
    const { result } = renderHook(() =>
      useRenewableResourceUrl('https://example.test/file.png'),
    );

    expect(result.current.url).toBe('https://example.test/file.png');
    expect(result.current.isResourceId).toBe(false);
    expect(sendEventAsync).not.toHaveBeenCalled();
  });

  it('resolves a persisted resource ID to a fresh URL', async () => {
    sendEventAsync.mockResolvedValue({
      download_url: 'https://storage.example/fresh',
    });
    const { result } = renderHook(() => useRenewableResourceUrl(RESOURCE_ID));

    await waitFor(() => {
      expect(result.current.url).toBe('https://storage.example/fresh');
    });
    expect(sendEventAsync).toHaveBeenCalledWith({
      event_name: 'resource:download_url',
      resource_id: RESOURCE_ID,
    });
  });

  it('does not let a stale lookup overwrite a newer value', async () => {
    let resolveLookup: ((value: { download_url: string }) => void) | undefined;
    sendEventAsync.mockReturnValue(
      new Promise((resolve) => {
        resolveLookup = resolve;
      }),
    );
    const { result, rerender } = renderHook(
      ({ value }) => useRenewableResourceUrl(value),
      { initialProps: { value: RESOURCE_ID } },
    );

    rerender({ value: 'https://example.test/new.png' });
    resolveLookup?.({ download_url: 'https://storage.example/stale' });

    await waitFor(() => {
      expect(result.current.url).toBe('https://example.test/new.png');
    });
  });
});
