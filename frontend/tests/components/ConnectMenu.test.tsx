// @vitest-environment jsdom
// The chat's Connect menu lists the ways into the same conversation. A texting app opens on a message that carries the
// link code until a phone is linked, then on a plain chat; email shows NoClick's address, claiming one the first time,
// renaming it in place and taking mail to it or not as the owner says, from the owner only or from anyone as the server
// reports; MCP opens the client setup guides.
import { act, cleanup, fireEvent, render, renderHook, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeAll, beforeEach, expect, it, vi } from 'vitest';

const { sendEventAsync } = vi.hoisted(() => ({ sendEventAsync: vi.fn() }));
vi.mock('~/lib/socket-sender', () => ({ sendEventAsync, sendEvent: vi.fn() }));
const signedIn = vi.hoisted(() => ({ email: 'owner@example.com' as string | undefined }));
vi.mock('react-router', async (importOriginal) => ({
    ...(await importOriginal<typeof import('react-router')>()),
    useRouteLoaderData: () => ({ user: { id: 'u1', email: signedIn.email } }),
}));
const device = vi.hoisted(() => ({ mobile: false, country: 'IN' as string | undefined }));
vi.mock('~/hooks/useIsMobile', () => ({ useIsMobile: () => device.mobile }));
vi.mock('~/hooks/useDetectedCountry', () => ({ useDetectedCountry: () => device.country }));

import { ConnectMenu } from '~/components/shell/ConnectMenu';
import { usePhoneLink } from '~/hooks/usePhoneLink';
import { refreshCoordinatorReach, useCoordinatorReach } from '~/hooks/useCoordinatorChat';

const WHATSAPP = '+14155550100';
const IMESSAGE = '+14155550111';
let reach: { phone: string | null; imessage: string | null; email: string | null; email_paused?: boolean; email_from_anyone?: boolean };
// What coordinator:email:inbound answers, when a test wants other than the switch's own word.
let inboundReply: ((on: boolean) => unknown) | null;
let linkedPhones: { phone: string; verified_at: string; source: string }[];
const TAKEN = 'taken';

beforeAll(() => {
    // Radix measures what it positions.
    globalThis.ResizeObserver ??= class {
        observe() {}
        unobserve() {}
        disconnect() {}
    } as unknown as typeof ResizeObserver;
});

/** The coordinator's reach is one store every surface shares: read it as this test has it. */
async function syncReach() {
    const { result, unmount } = renderHook(() => useCoordinatorReach());
    act(() => refreshCoordinatorReach());
    await waitFor(() => expect(result.current).toEqual(reach));
    unmount();
}

/** The linked numbers are one store every surface shares: read them as this test has them. */
async function syncPhones() {
    const { result, unmount } = renderHook(() => usePhoneLink());
    await waitFor(() => expect(result.current.phones).toEqual(linkedPhones));
    unmount();
}

beforeEach(async () => {
    device.mobile = false;
    device.country = 'IN';
    signedIn.email = 'owner@example.com';
    reach = { phone: WHATSAPP, imessage: IMESSAGE, email: null };
    inboundReply = null;
    linkedPhones = [];
    localStorage.clear();
    sendEventAsync.mockImplementation(async (request: { event_name?: string }) => {
        if (request.event_name === 'coordinator:open') return { conversation_id: 'coordinator:u1', reach };
        if (request.event_name === 'phone:status') return { configured: true, max_phones: 5, phones: linkedPhones };
        if (request.event_name === 'phone:link:code') return { code: 'NC-1234-5678', expires_in: 600 };
        if (request.event_name === 'coordinator:email:ensure') {
            reach = { ...reach, email: reach.email ?? 'owner@noclick.app' };
            return { address: reach.email };
        }
        if (request.event_name === 'coordinator:email:inbound') {
            const { on } = request as unknown as { on: boolean };
            if (inboundReply) return inboundReply(on);
            reach = { ...reach, email_paused: !on };
            return { address: reach.email, paused: !on };
        }
        if (request.event_name === 'coordinator:email:set') {
            const { name } = request as unknown as { name: string };
            if (name === TAKEN) return { error: `${TAKEN}@noclick.app is taken; pick another name.`, kind: 'email' };
            reach = { ...reach, email: `${name}@noclick.app` };
            return { address: reach.email };
        }
        return { error: 'unexpected' };
    });
    await syncPhones();
    await syncReach();
});
afterEach(() => {
    cleanup();
    sendEventAsync.mockReset();
});

async function openMenu(onAsk = vi.fn()) {
    render(<ConnectMenu onAsk={onAsk} />);
    await act(async () => fireEvent.click(screen.getByRole('button', { name: /Connect/ })));
    const menu = await screen.findByTestId('connect-menu');
    // The rows wait on the coordinator's numbers.
    await within(menu).findByText('WhatsApp');
    return { menu, onAsk };
}

const rowTitles = (menu: HTMLElement) => Array.from(menu.querySelectorAll('[data-menu-item]')).map((row) => row.querySelector('span:nth-child(2) > span')?.textContent);

it('reads the reach with where this browser is, the zone that replaces the one the owner’s number placed', () => {
    const opens = sendEventAsync.mock.calls.filter(([request]) => request.event_name === 'coordinator:open');
    expect(opens.at(-1)?.[0]).toMatchObject({ timezone: Intl.DateTimeFormat().resolvedOptions().timeZone });
});

it('lists the ways in, with the texting app most people where you are use first', async () => {
    const { menu } = await openMenu();
    expect(rowTitles(menu)).toEqual(['WhatsApp', 'iMessage', 'Email', 'MCP']);
    cleanup();

    device.country = 'US';
    const second = await openMenu();
    expect(rowTitles(second.menu)).toEqual(['iMessage', 'WhatsApp', 'Email', 'MCP']);
});

it('shows a laptop the code to scan, opening the app on the message that links the phone', async () => {
    const { menu } = await openMenu();
    fireEvent.click(within(menu).getByText('WhatsApp'));
    const open = await within(menu).findByRole('link', { name: /Open WhatsApp/ });
    expect(open.getAttribute('href')).toBe(`https://wa.me/14155550100?text=${encodeURIComponent('Link my NoClick account: NC-1234-5678')}`);
    expect(within(menu).getByRole('img', { name: /Scan to message NoClick on WhatsApp/ })).toBeTruthy();
    expect(within(menu).getByText(/links your phone to NoClick/)).toBeTruthy();
});

it('opens a plain chat once a phone is linked', async () => {
    linkedPhones = [{ phone: '+919800000000', verified_at: '2026-10-01T00:00:00Z', source: 'whatsapp' }];
    await syncPhones();
    sendEventAsync.mockClear();
    const { menu } = await openMenu();
    fireEvent.click(within(menu).getByText('iMessage'));
    await waitFor(() => expect(within(menu).getByRole('link', { name: /Open Messages/ }).getAttribute('href')).toBe(`sms:${IMESSAGE}`));
    expect(within(menu).getByText('Scan to open the chat on your phone.')).toBeTruthy();
    expect(sendEventAsync.mock.calls.some(([request]) => request.event_name === 'phone:link:code')).toBe(false);
});

it('opens the app itself on a phone', async () => {
    device.mobile = true;
    const { menu } = await openMenu();
    const whatsapp = await waitFor(() => {
        const row = within(menu).getByText('WhatsApp').closest('a');
        expect(row).not.toBeNull();
        return row!;
    });
    expect(whatsapp.getAttribute('href')).toContain('https://wa.me/14155550100?text=');
});

it('claims an address the first time Email opens', async () => {
    const { menu } = await openMenu();
    fireEvent.click(within(menu).getByText('Email'));
    expect((await within(menu).findByTestId('connect-email-address')).textContent).toBe('owner@noclick.app');
    expect(sendEventAsync.mock.calls.filter(([request]) => request.event_name === 'coordinator:email:ensure')).toHaveLength(1);
});

it('renames the address in place, keeping the edit open when the name is taken', async () => {
    reach = { ...reach, email: 'owner@noclick.app' };
    await syncReach();
    const { menu } = await openMenu();
    fireEvent.click(within(menu).getByText('Email'));
    fireEvent.click(await within(menu).findByRole('button', { name: 'Change' }));
    const field = within(menu).getByRole('textbox', { name: 'Address name' });
    expect((field as HTMLInputElement).value).toBe('owner');
    expect(within(menu).getByText('@noclick.app')).toBeTruthy();

    fireEvent.change(field, { target: { value: TAKEN } });
    fireEvent.submit(field.closest('form')!);
    expect((await within(menu).findByRole('alert')).textContent).toBe('taken@noclick.app is taken; pick another name.');

    fireEvent.change(field, { target: { value: 'Helper' } });
    fireEvent.submit(field.closest('form')!);
    expect((await within(menu).findByTestId('connect-email-address')).textContent).toBe('helper@noclick.app');
});

it('cancels an edit on Escape without closing the menu', async () => {
    reach = { ...reach, email: 'owner@noclick.app' };
    await syncReach();
    const { menu } = await openMenu();
    fireEvent.click(within(menu).getByText('Email'));
    fireEvent.click(await within(menu).findByRole('button', { name: 'Change' }));
    fireEvent.keyDown(within(menu).getByRole('textbox', { name: 'Address name' }), { key: 'Escape' });
    expect(await within(menu).findByTestId('connect-email-address')).toBeTruthy();
    expect(screen.getByTestId('connect-menu')).toBeTruthy();
});

it('keeps asking NoClick to name it as the quiet alternative', async () => {
    const { menu, onAsk } = await openMenu();
    fireEvent.click(within(menu).getByText('Email'));
    fireEvent.click(await within(menu).findByRole('button', { name: 'Ask NoClick to name it' }));
    expect(onAsk).toHaveBeenCalledWith('Pick a better name for your email address.');
    await waitFor(() => expect(screen.queryByTestId('connect-menu')).toBeNull());
});

it('reads the address again on open, since NoClick picks it in the conversation', async () => {
    reach = { ...reach, email: 'assistant@noclick.app' };
    const { menu } = await openMenu();
    expect(await within(menu).findByText('assistant@noclick.app')).toBeTruthy();
    fireEvent.click(within(menu).getByText('Email'));
    expect((await within(menu).findByTestId('connect-email-address')).textContent).toBe('assistant@noclick.app');
    expect((within(menu).getByRole('switch', { name: 'Answer emails' }) as HTMLButtonElement).getAttribute('aria-checked')).toBe('true');
    // The one sender it answers is named under the switch.
    expect(within(menu).getByTestId('connect-email-inbound-note').textContent).toMatch(/^Email it from owner@example\.com /);
    expect(within(menu).getByRole('link', { name: /Open mail/ }).getAttribute('href')).toBe('mailto:assistant@noclick.app');
});

it('says anyone can email it where the server lets anyone, even when the account has no email of its own', async () => {
    reach = { ...reach, email: 'owner@noclick.app', email_from_anyone: true };
    await syncReach();
    const { menu } = await openMenu();
    fireEvent.click(within(menu).getByText('Email'));
    expect((await within(menu).findByTestId('connect-email-inbound-note')).textContent).toBe(
        'Anyone can email it, and it replies on the same thread. Mail from owner@example.com shows here too.'
    );
    cleanup();

    signedIn.email = undefined;
    const reopened = (await openMenu()).menu;
    fireEvent.click(within(reopened).getByText('Email'));
    expect((await within(reopened).findByRole('switch', { name: 'Answer emails' })).getAttribute('aria-checked')).toBe('true');
    expect(within(reopened).getByTestId('connect-email-inbound-note').textContent).toBe('Anyone can email it, and it replies on the same thread.');
    expect(within(reopened).getByRole('button', { name: 'Add your email' })).toBeTruthy();
});

it('turns mail to the address off and on, and the menu says Off while it is', async () => {
    reach = { ...reach, email: 'owner@noclick.app' };
    await syncReach();
    const { menu } = await openMenu();
    fireEvent.click(within(menu).getByText('Email'));
    const toggle = await within(menu).findByRole('switch', { name: 'Answer emails' });
    expect(toggle.getAttribute('aria-checked')).toBe('true');

    await act(async () => fireEvent.click(toggle));
    expect(sendEventAsync.mock.calls.filter(([r]) => r.event_name === 'coordinator:email:inbound').map(([r]) => r.on)).toEqual([false]);
    expect(toggle.getAttribute('aria-checked')).toBe('false');
    expect(within(menu).getByTestId('connect-email-inbound-note').textContent).toBe('Mail to this address is ignored. The address stays yours.');
    // Nothing to write to while it ignores its mail.
    expect(within(menu).queryByRole('link', { name: /Open mail/ })).toBeNull();
    expect(within(menu).getByTestId('connect-email-address').textContent).toBe('owner@noclick.app');

    fireEvent.click(within(menu).getByRole('button', { name: /Back/ }));
    const row = (await within(menu).findByText('Email')).closest('[data-menu-item]') as HTMLElement;
    expect(within(row).getByText('Off')).toBeTruthy();

    fireEvent.click(within(menu).getByText('Email'));
    await act(async () => fireEvent.click(await within(menu).findByRole('switch', { name: 'Answer emails' })));
    expect(within(menu).getByRole('switch', { name: 'Answer emails' }).getAttribute('aria-checked')).toBe('true');
});

it('moves the switch at once, then lets the server have the last word', async () => {
    reach = { ...reach, email: 'owner@noclick.app' };
    await syncReach();
    const { menu } = await openMenu();
    fireEvent.click(within(menu).getByText('Email'));
    const toggle = await within(menu).findByRole('switch', { name: 'Answer emails' });

    let answer: (value: unknown) => void = () => {};
    inboundReply = () => new Promise((resolve) => (answer = resolve));
    await act(async () => fireEvent.click(toggle));
    expect(toggle.getAttribute('aria-checked')).toBe('false'); // before the server answers
    // The server kept it on (say another tab turned it back): its answer stands.
    await act(async () => answer({ address: 'owner@noclick.app', paused: false }));
    expect(toggle.getAttribute('aria-checked')).toBe('true');

    inboundReply = () => ({ error: 'Not authenticated' });
    await act(async () => fireEvent.click(toggle));
    expect(toggle.getAttribute('aria-checked')).toBe('true');
    expect((await within(menu).findByRole('alert')).textContent).toBe('Not authenticated');
});

it('reads whether mail is taken again on open, since another device can turn it off', async () => {
    reach = { ...reach, email: 'owner@noclick.app' };
    await syncReach();
    reach = { ...reach, email_paused: true }; // turned off elsewhere after this page read it
    const { menu } = await openMenu();
    const row = (await within(menu).findByText('Email')).closest('[data-menu-item]') as HTMLElement;
    expect(await within(row).findByText('Off')).toBeTruthy();
});

it('opens the MCP setup guides', async () => {
    const { menu } = await openMenu();
    fireEvent.click(within(menu).getByText('MCP'));
    expect(await screen.findByText('Connect over MCP')).toBeTruthy();
    expect(screen.queryByTestId('connect-menu')).toBeNull();
});
