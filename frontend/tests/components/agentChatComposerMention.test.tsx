// @vitest-environment jsdom
// Verifies the composer's @-mention menu preempts Enter-to-send (menu open →
// accept a file, not submit) and stays inert when no workspace files are passed
// (the public share page). Pure-detection logic lives in mentionToken.test.ts.

import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/react';
import { useState } from 'react';

vi.mock('~/hooks/useIsMobile', () => ({ useIsMobile: () => false }));

import { AgentChatComposer } from '~/components/chat/AgentChatComposer';

afterEach(cleanup);

function Harness({
  mentionFiles,
  onSubmit,
}: {
  mentionFiles?: { path: string }[];
  onSubmit: () => void;
}) {
  const [value, setValue] = useState('');
  return (
    <AgentChatComposer
      value={value}
      onChange={setValue}
      onSubmit={onSubmit}
      placeholder="Message"
      mentionFiles={mentionFiles}
      mentionMount="/workspace"
      onMentionRefresh={() => {}}
    />
  );
}

function typeToken(textarea: HTMLTextAreaElement, value: string, caret: number) {
  fireEvent.change(textarea, {
    target: { value, selectionStart: caret, selectionEnd: caret },
  });
}

describe('AgentChatComposer @-mention', () => {
  it('opens a menu on @ and Enter accepts a file instead of submitting', () => {
    const onSubmit = vi.fn();
    render(<Harness mentionFiles={[{ path: 'report.md' }]} onSubmit={onSubmit} />);
    const textarea = screen.getByPlaceholderText('Message') as HTMLTextAreaElement;

    typeToken(textarea, '@rep', 4);
    expect(screen.getByTestId('mention-menu')).toBeTruthy();

    fireEvent.keyDown(textarea, { key: 'Enter' });
    expect(onSubmit).not.toHaveBeenCalled();
    expect(textarea.value).toBe('/workspace/report.md ');
    expect(screen.queryByTestId('mention-menu')).toBeNull();
  });

  it('Enter submits normally when the menu is closed', () => {
    const onSubmit = vi.fn();
    render(<Harness mentionFiles={[{ path: 'report.md' }]} onSubmit={onSubmit} />);
    const textarea = screen.getByPlaceholderText('Message') as HTMLTextAreaElement;

    typeToken(textarea, 'hello', 5);
    expect(screen.queryByTestId('mention-menu')).toBeNull();
    fireEvent.keyDown(textarea, { key: 'Enter' });
    expect(onSubmit).toHaveBeenCalledTimes(1);
  });

  it('is inert with no workspace files: @ types literally, Enter submits', () => {
    const onSubmit = vi.fn();
    render(<Harness mentionFiles={[]} onSubmit={onSubmit} />);
    const textarea = screen.getByPlaceholderText('Message') as HTMLTextAreaElement;

    typeToken(textarea, '@rep', 4);
    expect(screen.queryByTestId('mention-menu')).toBeNull();
    fireEvent.keyDown(textarea, { key: 'Enter' });
    expect(onSubmit).toHaveBeenCalledTimes(1);
  });
});
