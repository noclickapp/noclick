// What stands in the canvas's drawing slots (slots.ts) when no host fills them: what a step is by its type, read from
// the platform API (the step form's read of a type, once a session per client); each step drawn as a plain step
// (nodes/PlainStep.tsx), a sticky note as a note; and a note's text drawn as a code repository's README is. (No build is
// known to be working on a step: slots.ts says so itself.)
import { lazy, Suspense, useMemo } from 'react';
import { getNodeIconMeta } from '@/lib/nodeIconRegistry';
import { useClient } from '@/sdk/client';
import { cn } from '@/ui/utils';
import { plainStepDefinition } from './nodes/PlainStep';
import { StickyNoteNode } from './nodes/StickyNoteNode';
import type { NodeDefinition } from './nodes/types';
import type { StepOutline, StepRoles } from './slots';
import { readStepType, useStepTypesSettled } from './slotStandards';

// ── what a step is, by its type ─────────────────────────────────────────────

/** What steps are by their type as `GET /v1/step_types/{type}` says, each type read the first time it's asked about;
 *  a type not read yet is neither a trigger nor a tool, and draws again as its read lands. */
export function useV1StepRoles(): StepRoles {
    const client = useClient();
    // A new reading each time another type lands, so what memoizes on it draws again too.
    const settled = useStepTypesSettled(client);
    return useMemo<StepRoles>(() => {
        const read = (type: string | null | undefined) => (type ? readStepType(client, type) : undefined);
        return {
            trigger: (type, operation) => {
                const known = read(type);
                if (!known) return false;
                return known.trigger || (!!operation && known.operations.some((op) => op.name === operation && op.trigger));
            },
            tool: (type) => read(type)?.kinds.includes('tool') ?? false,
            canonical: (type) => read(type)?.type ?? type,
        };
    }, [client, settled]);
}

// ── how each step type is drawn ─────────────────────────────────────────────
// Function declarations, as everything slots.ts reads from here at its declarations: a module that reads its slots
// (every part of the drawing) may be what loads slots.ts while this file hasn't run yet.

/** Every type drawn as it's met, with nothing to load first: a sticky note as a note, any other step as a plain step
 *  with what the catalog the host loaded says of it (its name, glyph and size). */
export function plainDrawingOf(type: string): NodeDefinition {
    return type === StickyNoteNode.type ? StickyNoteNode : plainStepDefinition(type);
}

/** What the catalog the host loaded says a type looks like, while its node loads. */
export function catalogOutline(type: string): StepOutline | undefined {
    const meta = getNodeIconMeta(type);
    return meta ? { dimensions: meta.dimensions, iconHtml: meta.iconHtml, iconColor: meta.iconColor } : undefined;
}

// ── a sticky note's text ────────────────────────────────────────────────────

// Loaded with the first note drawn: the README renderer, which a host that fills the slot never needs.
const ReadmeMarkdown = lazy(() =>
    import('@/screens/resources/CodeView').then((m) => ({
        default: ({ content, className }: { content: string; className?: string }) => <m.MarkdownDoc source={content} className={className} />,
    }))
);

/** A note's text drawn as a code repository's README is; its words as they are while that loads. */
export function NoteAsReadme({ content, className }: { content: string; className?: string }) {
    return (
        <Suspense fallback={<div className={cn('whitespace-pre-wrap break-words', className)}>{content}</div>}>
            <ReadmeMarkdown content={content} className={className} />
        </Suspense>
    );
}
