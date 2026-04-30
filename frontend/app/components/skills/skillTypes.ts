/**
 * Shared TypeScript types and small helpers for the Skills feature.
 * Keeps the SkillsList / SkillRow / SkillEditor components decoupled
 * and ready to be reused outside the debug context.
 */

export type SkillSummary = {
    id: string;
    owner_id: string | null;
    organization_id: string | null;
    is_system: boolean;
    name: string;
    description: string;
    has_text: boolean;
    has_workflow: boolean;
    enabled: boolean;
    muted: boolean;
    created_at: string;
    updated_at: string;
};

export type SkillDetail = SkillSummary & {
    body_text: string | null;
    body_workflow: { nodes?: unknown[]; edges?: unknown[]; [k: string]: unknown } | null;
    display_metadata: Record<string, unknown>;
};

export type SkillListResponse = {
    owned: SkillSummary[];
    shared: SkillSummary[];
    system: SkillSummary[] | null;
};

export type SkillScope = 'owned' | 'shared' | 'system';

/** Whether the current viewer can edit / delete this skill. */
export function canEditSkill(skill: SkillSummary, scope: SkillScope): boolean {
    if (scope === 'shared') return false; // shared skills are read-only by default in v1
    return true;
}

export function canDeleteSkill(skill: SkillSummary, scope: SkillScope): boolean {
    if (scope === 'shared') return false;
    return true;
}
