// @vitest-environment happy-dom
// Settings → Skills: each skill's row turns it on or off with the product's switch, which a screen reader names and
// a tap or a key toggles without opening the skill behind the row.
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';

const { sent } = vi.hoisted(() => ({ sent: [] as Record<string, unknown>[] }));
vi.mock('~/lib/socket-sender', () => ({
    sendEventWithCallback: (event: Record<string, unknown>, done: (resp: unknown) => void) => {
        sent.push(event);
        if (event.event_name === 'skill:list') done({ owned: [SKILL], shared: [], system: [] });
        else done({});
        return () => undefined;
    },
}));
vi.mock('~/components/skills/SkillEditor', () => ({ SkillEditor: () => <div data-testid="skill-editor" /> }));

import { SkillsSettings } from '~/components/settings/SkillsSettings';

const SKILL = { id: 's1', owner_id: 'u-1', organization_id: null, is_system: false, name: 'Brand voice', description: 'How we write.', has_text: true, has_workflow: false, enabled: true, muted: false, created_at: '2026-11-14T09:00:00Z', updated_at: '2026-11-14T09:00:00Z' };

afterEach(() => {
    cleanup();
    sent.length = 0;
});

it('turns a skill off with the product’s switch, without opening it', async () => {
    await act(async () => {
        render(<SkillsSettings />);
    });
    const toggle = await screen.findByRole('switch', { name: 'Disable' });
    expect(toggle.getAttribute('aria-checked')).toBe('true');
    fireEvent.click(toggle);
    expect(sent.find((e) => e.event_name === 'skill:update')).toEqual({ event_name: 'skill:update', skill_id: 's1', enabled: false });
    fireEvent.keyDown(toggle, { key: 'Enter' });
    expect(screen.queryByTestId('skill-editor')).toBeNull();
});
