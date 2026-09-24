// @vitest-environment jsdom
// Standalone credential approvals have no workflow to display. Keep both dashboard
// row sizes renderable without inventing a workflow or losing the review action.
import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import { AttentionRow } from './sections';
import type { AttentionItem } from './types';

vi.mock('~/components/dashboard/AskAnswer', () => ({ AskAnswer: () => null }));
afterEach(cleanup);

const item: AttentionItem = {
    id: 'approval:standalone',
    kind: 'approval',
    title: 'Send email · Personal Gmail',
    detail: 'Review this call before it runs',
    workflow: null,
    createdAt: '2026-09-24T10:00:00Z',
    link: '/credential/approval/standalone',
    meta: { credentialAction: true, approvalId: 'standalone' },
};

it.each([false, true])('renders a standalone approval when dense is %s', (dense) => {
    render(<AttentionRow item={item} now="2026-09-24T10:05:00Z" dense={dense} />);
    expect(screen.getByText(item.title)).toBeTruthy();
    expect(screen.getByText('5m ago')).toBeTruthy();
    if (!dense) expect(screen.getByRole('button', { name: 'Review action' })).toBeTruthy();
});
