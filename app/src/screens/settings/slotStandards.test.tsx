// @vitest-environment happy-dom
// What Settings shows in its slots: with no host, none of the sections whose body is the deployment's (Settings leaves
// them out), and Developer as the console's way in alone; with a host, each section it fills, and the older keys it
// kept under the console's row.
import { cleanup, render, renderHook, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { afterEach, describe, expect, it } from 'vitest';
import { fill, standing } from '@/slots';
import { DeveloperView } from './developer';
import { visibleSections } from './sections';
import { BILLING, MEMBERS, OLDER_KEYS, PHONE, POPUPS, SKILLS, useHostSections } from './slots';

const SECTION_SLOTS = [BILLING, MEMBERS, PHONE, SKILLS, POPUPS];

afterEach(() => {
    cleanup();
    for (const section of SECTION_SLOTS) fill(section, null);
    fill(OLDER_KEYS, null);
});

const everything = { inOrganization: true, hasMembers: true, phoneLinking: true };

describe('with no host', () => {
    it('draws none of the deployment’s sections, and Settings leaves each out', () => {
        expect(SECTION_SLOTS.map((section) => standing(section))).toEqual([null, null, null, null, null]);
        const { result } = renderHook(() => useHostSections());
        expect(result.current.bodies).toEqual({});
        expect(result.current.unfilled).toEqual(['billing', 'organization', 'phone', 'skills', 'popups']);
        expect(visibleSections(everything, result.current.unfilled).map((s) => s.id)).toEqual(['usage', 'notifications', 'developer']);
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
        const { result } = renderHook(() => useHostSections());
        expect(result.current.bodies).toEqual({ billing: Plan, phone: Phone });
        expect(result.current.unfilled).toEqual(['organization', 'skills', 'popups']);
        expect(visibleSections(everything, result.current.unfilled).map((s) => s.id)).toEqual(['usage', 'billing', 'notifications', 'phone', 'developer']);
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
