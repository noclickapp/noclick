// Which of Settings' sections an account sees, and the groups its list shows them in.
import { describe, expect, it } from 'vitest';
import { SETTINGS_GROUPS, SETTINGS_SECTION_DEFS, groupSections, visibleSections, type SectionContext } from './sections';

const PERSONAL: SectionContext = { inOrganization: false, hasMembers: false, phoneLinking: false };
const ids = (context: SectionContext, hidden?: string[]) => visibleSections(context, hidden).map((s) => s.id);

describe('the sections an account sees', () => {
    it('are every section, in the table’s order, where everything holds', () => {
        expect(ids({ inOrganization: true, hasMembers: true, phoneLinking: true })).toEqual(SETTINGS_SECTION_DEFS.map((s) => s.id));
    });

    it('leave Members out where the workspace has nobody to show, and Phone where numbers can’t be linked', () => {
        expect(ids(PERSONAL)).not.toContain('organization');
        expect(ids(PERSONAL)).not.toContain('phone');
        expect(ids({ ...PERSONAL, hasMembers: true, phoneLinking: true })).toEqual(expect.arrayContaining(['organization', 'phone']));
    });

    it('leave out what the host shows as a page of its own', () => {
        expect(ids(PERSONAL, ['developer', 'published'])).not.toContain('developer');
        expect(ids(PERSONAL, ['developer'])).toContain('usage');
    });

    it('say who Members is for: an organization’s people, or inviting some to a personal workspace', () => {
        const members = (inOrganization: boolean) => visibleSections({ inOrganization, hasMembers: true, phoneLinking: false }).find((s) => s.id === 'organization');
        expect(members(true)?.description).toBe('Who’s in this workspace and how they sign in');
        expect(members(false)?.description).toBe('Invite people to your workspace');
    });
});

describe('the list’s groups', () => {
    it('hold every section once', () => {
        const grouped = SETTINGS_GROUPS.flatMap((g) => g.sections);
        expect([...grouped].sort()).toEqual(SETTINGS_SECTION_DEFS.map((s) => s.id).sort());
    });

    it('keep their order and leave out a group with nothing left in it', () => {
        const groups = groupSections(visibleSections(PERSONAL, ['usage', 'workstreams', 'billing', 'organization']));
        expect(groups.map((g) => g.label)).toEqual(['Preferences', 'Build']);
        expect(groups[0].items.map((s) => s.id)).toEqual(['notifications', 'popups']);
    });
});
