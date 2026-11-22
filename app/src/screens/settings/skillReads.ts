// Settings → Skills' read: the skills NoClick's builder loads for the account, read with GET /v1/builder_skills through
// the client its host hands it (`ClientProvider`), made, switched and deleted through the same API. Read again after
// each change here, after the editor closes or saves (a host's editor writes its own way), and when the page comes back
// into view; never on a timer.
import { useCallback, useState } from 'react';
import { BuilderSkill } from 'noclick';
import { useClient } from '@/sdk/client';
import { invalidateV1, useV1 } from '@/sdk/useV1';

/** The read's key in the client's cache. */
export const SKILLS_READ = 'settings:builder-skills';

/** Reads the skills again wherever they're drawn: what a host calls when it hears of a change its own way. */
export function readSkillsAgain(): void {
    invalidateV1(SKILLS_READ);
}

export interface SkillsState {
    /** The account's own and those shared with it; null while they're first read. */
    owned: BuilderSkill[] | null;
    shared: BuilderSkill[] | null;
    /** What the API last refused, until it's dismissed. */
    error: string | null;
    dismissError: () => void;
    /** Makes one by its name, resolving to it (null when refused). */
    create: (name: string) => Promise<BuilderSkill | null>;
    /** Turns one on or off for the account: its own `enabled`, or its mute where it's shared with the account. */
    toggleActive: (skill: BuilderSkill) => Promise<void>;
    remove: (skill: BuilderSkill) => Promise<void>;
    /** Reads them again: after the editor closes or saves. */
    refresh: () => void;
}

const why = (error: unknown) => (error instanceof Error ? error.message : String(error));

export function useBuilderSkills(): SkillsState {
    const client = useClient();
    const read = useV1(SKILLS_READ, () => BuilderSkill.list({ client }), { client });
    const [refused, setRefused] = useState<string | null>(null);
    const { refresh } = read;

    // Each change, then the list as it stands; a refusal is shown above it until it's dismissed.
    const change = useCallback(
        async <T>(write: () => Promise<T>): Promise<T | null> => {
            try {
                const done = await write();
                await refresh();
                return done;
            } catch (error) {
                setRefused(why(error));
                return null;
            }
        },
        [refresh]
    );

    const all = read.data ?? null;
    const loadError = read.error && !all ? why(read.error) : null;
    return {
        owned: all && all.filter((skill) => skill.scope === 'owned'),
        shared: all && all.filter((skill) => skill.scope === 'shared'),
        error: refused ?? loadError,
        dismissError: () => setRefused(null),
        create: (name) => change(() => BuilderSkill.create({ name, description: '', enabled: true }, { client })),
        toggleActive: async (skill) => {
            await change(() => (skill.scope === 'shared' ? skill.update({ muted: !skill.muted }, { client }) : skill.update({ enabled: !skill.enabled }, { client })));
        },
        remove: async (skill) => {
            await change(() => skill.delete({ client }));
        },
        refresh: () => void refresh(),
    };
}
