// @vitest-environment happy-dom
// The model picker in an agent's conversation, on a phone and on a laptop, over the fake /v1 through the real SDK. A
// phone opens it as a sheet over the page, on its models: the search isn't focused, so no keyboard covers them. A
// laptop opens it as a popover with the search ready to type in.
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { PhoneBarSlotProvider } from '@/ui/phoneBar';
import { WorkProviders } from '../agents/fixtures/providers';
import { AgentConversation } from './AgentConversation';
import { AGENT_ID, fakeWorkAgent } from './fixtures/workAgent';

beforeEach(() => vi.stubGlobal('fetch', async () => new Response(null, { status: 404 })));
afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
});

async function openPicker({ phone }: { phone: boolean }) {
    const conversation = <AgentConversation agentId={AGENT_ID} conversation="main" onOpenProfile={() => undefined} onOpenMachine={() => undefined} />;
    render(
        <WorkProviders client={fakeWorkAgent().client}>
            {phone ? (
                <PhoneBarSlotProvider slot={null} lead={null} setLeadTaken={() => undefined}>
                    {conversation}
                </PhoneBarSlotProvider>
            ) : (
                conversation
            )}
        </WorkProviders>
    );
    fireEvent.click(await screen.findByRole('button', { name: /^Model: / }));
    return screen.findByRole('listbox', { name: 'Models' });
}

it('opens as a sheet over the page on a phone, on its models and not in the search', async () => {
    const models = await openPicker({ phone: true });
    const sheet = screen.getByRole('dialog', { name: 'Model' });
    expect(sheet.contains(models)).toBe(true);
    // The sheet's layer covers the page; the laptop's popover is not what opened.
    expect(sheet.closest('.fixed.inset-0')).toBeTruthy();
    expect(models.closest('[data-radix-popper-content-wrapper]')).toBeNull();
    expect(document.activeElement).not.toBe(within(sheet).getByRole('textbox', { name: 'Search models' }));
});

it('opens as a popover on a laptop, ready to search', async () => {
    const models = await openPicker({ phone: false });
    expect(screen.queryByRole('dialog', { name: 'Model' })).toBeNull();
    expect(models.closest('[data-radix-popper-content-wrapper]')).toBeTruthy();
    expect(document.activeElement).toBe(screen.getByRole('textbox', { name: 'Search models' }));
});
