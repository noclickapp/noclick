// @vitest-environment happy-dom
// Settings in the phone shell: a link to a section (an email's or a notice's `?section=`) opens that section, whether
// Settings is opening or already open, with the bar's back going to the list; Settings without a section is the list.
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { useState, type ReactNode } from 'react';
import { createMemoryRouter, RouterProvider, useLocation } from 'react-router';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { PhoneBarSlotProvider } from '~/components/shell/AppShell';
import { createTabSwitchHandler, type SettingsSection, type TabSwitchEventDetail } from '~/lib/navigation';
import { Settings } from './Settings';

vi.mock('~/hooks/useOrgContext', () => ({ useOrgContext: () => [{ id: null, isPersonalWorkspace: true }, () => undefined] }));
vi.mock('~/hooks/useInstanceCapabilities', () => ({ useInstanceCapabilities: () => ({ billing: true }) }));
vi.mock('~/hooks/usePhoneLinking', () => ({ usePhoneLinkingAvailable: () => false }));
// Each section's body, by name: what's under test is which one opens.
const { stub } = vi.hoisted(() => ({ stub: (name: string) => () => <div data-testid={`section-${name}`} /> }));
vi.mock('~/components/usage/page/UsagePage', () => ({ UsagePage: stub('usage') }));
vi.mock('~/components/settings/PlanSection', () => ({ PlanSection: stub('billing') }));
vi.mock('~/components/organization/OrganizationSettings', () => ({ OrganizationSettings: stub('organization') }));
vi.mock('~/components/settings/CredentialsSettings', () => ({ CredentialsSettings: stub('credentials') }));
vi.mock('~/components/settings/DeveloperSettings', () => ({ DeveloperSettings: stub('developer') }));
vi.mock('~/components/settings/InstanceOAuthSettings', () => ({ InstanceOAuthSettings: stub('oauth-apps') }));
vi.mock('~/components/settings/InstanceProviderKeysSettings', () => ({ InstanceProviderKeysSettings: () => null }));
vi.mock('~/components/settings/NotificationsSettings', () => ({ NotificationsSettings: stub('notifications') }));
vi.mock('~/components/settings/PhoneSettings', () => ({ PhoneSettings: stub('phone') }));
vi.mock('~/components/settings/PopupPreferencesSettings', () => ({ PopupPreferencesSettings: stub('popups') }));
vi.mock('~/components/settings/SkillsSettings', () => ({ SkillsSettings: stub('skills') }));

afterEach(cleanup);

/** The phone shell's bar, its lead holding the way back. */
function PhoneBar({ children }: { children: ReactNode }) {
    const [lead, setLead] = useState<HTMLElement | null>(null);
    return (
        <>
            <div ref={setLead} data-testid="phone-bar-lead" />
            <PhoneBarSlotProvider slot={null} lead={lead} setLeadTaken={() => undefined}>
                {children}
            </PhoneBarSlotProvider>
        </>
    );
}

function Address() {
    return <output data-testid="address">{useLocation().search}</output>;
}

/** Settings at `url` in the phone shell, opened (as the dashboard does) on `initialSection`: 'usage' unless a link
 *  named another and the dashboard had already read it. */
function show(url: string, initialSection: SettingsSection = 'usage') {
    const router = createMemoryRouter(
        [
            {
                path: '*',
                element: (
                    <PhoneBar>
                        <Settings initialSection={initialSection} hiddenSections={['credentials']} />
                        <Address />
                    </PhoneBar>
                ),
            },
        ],
        { initialEntries: [url] }
    );
    render(<RouterProvider router={router} />);
    return router;
}

const opened = () => screen.queryAllByTestId(/^section-/).map((el) => el.dataset.testid);
const list = () => screen.queryByRole('button', { name: /Popups/ });
const address = () => new URLSearchParams(screen.getByTestId('address').textContent ?? '');

describe('Settings on a phone', () => {
    it('opens the section a link names', () => {
        show('/dashboard?tab=settings&section=popups', 'popups');
        expect(opened()).toEqual(['section-popups']);
        expect(list()).toBeNull();
    });

    it('opens Usage when a link names it, though Usage is also what Settings opens on a laptop by default', () => {
        show('/dashboard?tab=settings&section=usage');
        expect(opened()).toEqual(['section-usage']);
    });

    it('opens the linked section when Settings opened before the link was read', () => {
        show('/dashboard?tab=settings&section=popups', 'usage');
        expect(opened()).toEqual(['section-popups']);
    });

    it('follows a link to another section while Settings is already open', async () => {
        const router = show('/dashboard?tab=settings');
        expect(list()).toBeTruthy();
        await act(() => router.navigate('/dashboard?tab=settings&section=notifications'));
        expect(opened()).toEqual(['section-notifications']);
    });

    it('is the list without a section, and a section opens from it and goes back to it', () => {
        show('/dashboard?tab=settings');
        expect(opened()).toEqual([]);
        fireEvent.click(list()!);
        expect(opened()).toEqual(['section-popups']);
        expect(address().get('section')).toBe('popups');
        fireEvent.click(screen.getByRole('button', { name: 'Settings' }));
        expect(opened()).toEqual([]);
        expect(list()).toBeTruthy();
        expect(address().get('section')).toBeNull();
        expect(address().get('tab')).toBe('settings');
    });

    it('goes back to the list from a linked section', () => {
        show('/dashboard?tab=settings&section=popups');
        fireEvent.click(screen.getByRole('button', { name: 'Settings' }));
        expect(list()).toBeTruthy();
        expect(address().get('section')).toBeNull();
    });

    it('shows the list for a section this account doesn’t have here', () => {
        show('/dashboard?tab=settings&section=credentials');
        expect(opened()).toEqual([]);
        expect(list()).toBeTruthy();
    });
});

describe('a jump to Settings', () => {
    /** The address after the dashboard's page switch handles `detail`, from `from`. */
    const after = (detail: TabSwitchEventDetail, from = 'tab=chat') => {
        let params = new URLSearchParams(from);
        const onSwitch = createTabSwitchHandler({ setSelectedTab: () => undefined, setSettingsSection: () => undefined, setSearchParams: (update) => void (params = update(params)) });
        onSwitch(new CustomEvent('noclick:switch-tab', { detail }));
        return params;
    };

    it('names the section it opens', () => {
        expect(after({ tab: 'settings', section: 'notifications' }).get('section')).toBe('notifications');
        expect(after({ tab: 'settings', section: 'usage' }).get('section')).toBe('usage');
    });

    it('names none without one, so a phone opens the list', () => {
        const params = after({ tab: 'settings' }, 'tab=settings&section=notifications&orgTab=sso');
        expect(params.get('tab')).toBe('settings');
        expect(params.has('section')).toBe(false);
        expect(params.has('orgTab')).toBe(false);
    });
});
