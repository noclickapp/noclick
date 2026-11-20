// @vitest-environment happy-dom
// Settings' parts: the frame on a laptop and on a phone, in and out of the phone shell; the rows every section is built
// from; and Notifications' switches.
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { useState, type ReactNode } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { PhoneBarSlotProvider } from '@/ui/phoneBar';
import { NOTIFICATION_CATEGORIES, NotificationsView } from './notifications';
import { SettingsEmpty, SettingsGroup, SettingsHeader, SettingsRow } from './parts';
import { groupSections, visibleSections, type SettingsSectionId } from './sections';
import { SettingsFrame } from './SettingsFrame';

let viewport = 1280;

beforeEach(() => {
    viewport = 1280;
    window.matchMedia = ((query: string) => {
        const max = /max-width:\s*(\d+)px/.exec(query);
        return {
            matches: max ? viewport <= Number(max[1]) : false,
            media: query,
            onchange: null,
            addEventListener: () => undefined,
            removeEventListener: () => undefined,
            addListener: () => undefined,
            removeListener: () => undefined,
            dispatchEvent: () => false,
        };
    }) as typeof window.matchMedia;
});
afterEach(cleanup);

const GROUPS = groupSections(visibleSections({ inOrganization: false, hasMembers: true, phoneLinking: true }));

function frame(open: { active?: SettingsSectionId; phoneSection?: SettingsSectionId | null } = {}, wrap: (page: ReactNode) => ReactNode = (page) => page) {
    const onSelect = vi.fn();
    const onClosePhone = vi.fn();
    const shortcutFor = vi.fn(() => undefined);
    render(
        <>
            {wrap(
                <SettingsFrame
                    groups={GROUPS}
                    active={open.active ?? 'usage'}
                    phoneSection={open.phoneSection ?? null}
                    onSelect={onSelect}
                    onClosePhone={onClosePhone}
                    renderSection={(id) => <p data-testid="section">{id}</p>}
                    shortcutFor={shortcutFor}
                />
            )}
        </>
    );
    return { onSelect, onClosePhone, shortcutFor };
}

/** The phone shell's bar, its lead holding the way back. */
function PhoneBar({ children }: { children: ReactNode }) {
    const [lead, setLead] = useState<HTMLElement | null>(null);
    return (
        <>
            <div ref={setLead} data-testid="bar-lead" />
            <PhoneBarSlotProvider slot={null} lead={lead} setLeadTaken={() => undefined}>
                {children}
            </PhoneBarSlotProvider>
        </>
    );
}

describe('the frame on a laptop', () => {
    it('lists the groups in their column beside the open section, which it marks', () => {
        const { shortcutFor } = frame({ active: 'notifications' });
        const column = screen.getByRole('navigation', { name: 'Settings' });
        expect(within(column).getByText('Workspace')).toBeTruthy();
        expect(within(column).getByText('Preferences')).toBeTruthy();
        expect(within(column).getByText('Build')).toBeTruthy();
        expect(within(column).getByRole('button', { name: 'Notifications' }).getAttribute('aria-current')).toBe('page');
        expect(screen.getByTestId('section').textContent).toBe('notifications');
        expect(shortcutFor).toHaveBeenCalledWith('notifications');
    });

    it('opens a section from the column', () => {
        const { onSelect } = frame();
        fireEvent.click(within(screen.getByRole('navigation', { name: 'Settings' })).getByRole('button', { name: 'Popups' }));
        expect(onSelect).toHaveBeenCalledWith('popups');
    });
});

describe('the frame on a phone', () => {
    beforeEach(() => {
        viewport = 390;
    });

    it('is the grouped list, each section with what it’s for, under the page’s own title', () => {
        const { onSelect } = frame();
        expect(screen.queryByRole('navigation')).toBeNull();
        expect(screen.getByRole('heading', { level: 1, name: 'Settings' })).toBeTruthy();
        expect(screen.getByRole('button', { name: /Phone\s*Link your number for WhatsApp and calls/ })).toBeTruthy();
        fireEvent.click(screen.getByRole('button', { name: /Popups/ }));
        expect(onSelect).toHaveBeenCalledWith('popups');
        expect(screen.queryByTestId('section')).toBeNull();
    });

    it('opens a section over the list with its own way back', () => {
        const { onClosePhone } = frame({ phoneSection: 'popups' });
        expect(screen.getByTestId('section').textContent).toBe('popups');
        fireEvent.click(screen.getByRole('button', { name: 'Settings' }));
        expect(onClosePhone).toHaveBeenCalled();
    });
});

describe('the frame in the phone shell', () => {
    it('leaves the title to the shell’s bar', () => {
        frame({}, (page) => <PhoneBar>{page}</PhoneBar>);
        expect(screen.queryByRole('heading', { level: 1 })).toBeNull();
        expect(screen.getByRole('button', { name: /Notifications/ })).toBeTruthy();
    });

    it('puts a section’s way back in the bar, not the page', () => {
        const { onClosePhone } = frame({ phoneSection: 'notifications' }, (page) => <PhoneBar>{page}</PhoneBar>);
        const bar = screen.getByTestId('bar-lead');
        const back = within(bar).getByRole('button', { name: 'Settings' });
        expect(screen.getAllByRole('button', { name: 'Settings' }).filter((b) => !bar.contains(b))).toEqual([]);
        fireEvent.click(back);
        expect(onClosePhone).toHaveBeenCalled();
    });
});

describe('a section’s rows', () => {
    it('name each setting and what it does, its control beside them, and a note under the group', () => {
        render(
            <>
                <SettingsHeader title="Popups" description="Choose which appear." />
                <SettingsGroup note="Changes apply at once.">
                    <SettingsRow label="Run results" description="After a run finishes." control={<button type="button">Turn off</button>} />
                </SettingsGroup>
                <SettingsGroup>
                    <SettingsEmpty>Nothing here yet.</SettingsEmpty>
                </SettingsGroup>
            </>
        );
        expect(screen.getByRole('heading', { level: 2, name: 'Popups' })).toBeTruthy();
        expect(screen.getByText('Choose which appear.')).toBeTruthy();
        expect(screen.getByText('After a run finishes.')).toBeTruthy();
        expect(screen.getByRole('button', { name: 'Turn off' })).toBeTruthy();
        expect(screen.getByText('Changes apply at once.')).toBeTruthy();
        expect(screen.getByText('Nothing here yet.')).toBeTruthy();
    });
});

describe('Notifications', () => {
    it('has a switch for each category, on unless it’s read off', () => {
        render(<NotificationsView prefs={{ digest: false }} onToggle={() => undefined} />);
        const switches = screen.getAllByRole('switch');
        expect(switches).toHaveLength(NOTIFICATION_CATEGORIES.length);
        expect(screen.getByRole('switch', { name: 'Weekly digest' }).getAttribute('aria-checked')).toBe('false');
        expect(screen.getByRole('switch', { name: 'Balance' }).getAttribute('aria-checked')).toBe('true');
    });

    it('says which category a switch turns off', () => {
        const onToggle = vi.fn();
        render(<NotificationsView prefs={{}} onToggle={onToggle} />);
        fireEvent.click(screen.getByRole('switch', { name: 'Approvals' }));
        expect(onToggle).toHaveBeenCalledWith('approvals', false);
    });

    it('holds the switches while the preferences are read, and shows what its host says above them', () => {
        render(<NotificationsView prefs={null} onToggle={() => undefined} notice={<p>Nothing sends mail here yet.</p>} />);
        expect(screen.getAllByRole('switch').every((s) => s.hasAttribute('disabled'))).toBe(true);
        expect(screen.getByText('Nothing sends mail here yet.')).toBeTruthy();
    });

    it('names each category once', () => {
        const keys = NOTIFICATION_CATEGORIES.map((c) => c.key);
        expect(new Set(keys).size).toBe(keys.length);
    });
});
