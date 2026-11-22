// @vitest-environment happy-dom
// What Settings shows in its slots: with no host, the app's own sections (Usage, Workstreams, Plan and billing,
// Notifications, Phone, Popups, Skills, Developer as the console's way in alone) and none of those whose body is only a
// deployment's (Settings leaves them out); with a host, each section it fills, and the older keys it kept under the
// console's row.
import { cleanup, render, renderHook, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { afterEach, describe, expect, it } from 'vitest';
import { fill, standing } from '@/slots';
import { UsagePage } from '@/screens/usage/UsagePage';
import { BillingStandard } from './billing';
import { DeveloperSection, DeveloperView } from './developer';
import { NotificationsSection } from './notifications';
import { PhoneSection } from './phone';
import { PopupsSection } from './popups';
import { SkillsSection } from './skills';
import { visibleSections } from './sections';
import { BILLING, DEVELOPER, MEMBERS, NOTIFICATIONS, OLDER_KEYS, PHONE, POPUPS, SKILLS, USAGE, WORKSTREAMS, useSectionBodies } from './slots';
import { WorkstreamsSection } from './workstreams';

const SECTION_SLOTS = [USAGE, WORKSTREAMS, BILLING, MEMBERS, SKILLS, NOTIFICATIONS, PHONE, POPUPS, DEVELOPER];

afterEach(() => {
    cleanup();
    for (const section of SECTION_SLOTS) fill(section, section.standard);
    fill(OLDER_KEYS, OLDER_KEYS.standard);
});

const everything = { inOrganization: true, hasMembers: true, phoneLinking: true };

describe('with no host', () => {
    it('draws the app’s own sections and none of the deployment’s, which Settings leaves out', () => {
        expect(SECTION_SLOTS.map((section) => standing(section))).toEqual([
            UsagePage, WorkstreamsSection, BillingStandard, null, SkillsSection, NotificationsSection, PhoneSection, PopupsSection, DeveloperSection,
        ]);
        const { result } = renderHook(() => useSectionBodies());
        expect(result.current.bodies).toEqual({
            usage: UsagePage, workstreams: WorkstreamsSection, billing: BillingStandard, skills: SkillsSection, notifications: NotificationsSection,
            phone: PhoneSection, popups: PopupsSection, developer: DeveloperSection,
        });
        expect(result.current.unfilled).toEqual(['organization']);
        expect(visibleSections(everything, result.current.unfilled).map((s) => s.id)).toEqual([
            'usage', 'workstreams', 'billing', 'skills', 'notifications', 'phone', 'popups', 'developer',
        ]);
    });

    it('opens the developer console from Developer, with nothing under it', () => {
        render(
            <MemoryRouter>
                <DeveloperView consoleHref="/developers" />
            </MemoryRouter>
        );
        expect(screen.getByRole('heading', { level: 2, name: 'Developer' })).toBeTruthy();
        expect(screen.getByRole('link', { name: 'Open console' }).getAttribute('href')).toBe('/developers');
        expect(screen.queryByText('Older keys')).toBeNull();
    });
});

describe('with a host', () => {
    it('draws each section it fills and lists it', () => {
        const Plan = () => <p>The plan</p>;
        const Phone = () => <p>Linked numbers</p>;
        fill(BILLING, Plan);
        fill(PHONE, Phone);
        const { result } = renderHook(() => useSectionBodies());
        expect(result.current.bodies).toEqual({
            usage: UsagePage, workstreams: WorkstreamsSection, billing: Plan, skills: SkillsSection, notifications: NotificationsSection, phone: Phone,
            popups: PopupsSection, developer: DeveloperSection,
        });
        expect(result.current.unfilled).toEqual(['organization']);
        expect(visibleSections(everything, result.current.unfilled).map((s) => s.id)).toEqual([
            'usage', 'workstreams', 'billing', 'skills', 'notifications', 'phone', 'popups', 'developer',
        ]);
    });

    it('shows the older keys it kept under the console’s row', () => {
        fill(OLDER_KEYS, () => <p>Older keys</p>);
        render(
            <MemoryRouter>
                <DeveloperView consoleHref="/dashboard/developers" />
            </MemoryRouter>
        );
        expect(screen.getByRole('link', { name: 'Open console' }).getAttribute('href')).toBe('/dashboard/developers');
        expect(screen.getByText('Older keys')).toBeTruthy();
    });
});
