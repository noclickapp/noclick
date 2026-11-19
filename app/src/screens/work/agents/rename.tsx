// Renaming an agent, wherever Work offers it: its name on its profile (click or tap it to edit it in place), Rename
// in its ⋯ menus (the Agents list, Resources → Agents) and /rename in its conversation. One write (PATCH
// /v1/agents/{id} {name}), one set of rules (a name of at most 100 characters that no other agent has or went by) and
// one way of saying what's wrong. Its old name keeps reaching it (`formerNames`); a NoClick, and an agent built in the
// app, keep their names, so neither is offered it.
import { useEffect, useId, useRef, useState, type MutableRefObject, type ReactNode } from 'react';
import { Pencil } from 'lucide-react';
import { Agent, NoClickError } from 'noclick';
import { invalidateV1 } from '@/sdk/useV1';
import { BUTTON_GHOST, BUTTON_PRIMARY } from '@/ui/buttons';
import { ShellDialog } from '@/ui/ShellDialog';
import { cn } from '@/ui/utils';
import { useWorkClient } from '../client';
import { rereadAgent } from '../profile/reads';
import { AGENTS_KEY, keptByNoClick, STATES_KEY } from './reads';

/** As long as an agent's name may be (the platform's own limit). */
export const MAX_AGENT_NAME = 100;

/** Whether Work offers to rename `agent`: never a NoClick (its name is how it's found), nor an agent built in the app
 *  (`node:` ids: its automation names it). */
export const renamable = (agent: { id: string; noclick?: unknown }): boolean => !keptByNoClick(agent) && !agent.id.startsWith('node:');

/** What's wrong with `name` before it's sent, in plain words; null when nothing is. */
export function nameProblem(name: string): string | null {
    if (!name.trim()) return 'Give it a name.';
    if (name.trim().length > MAX_AGENT_NAME) return `Keep it to ${MAX_AGENT_NAME} characters or fewer.`;
    return null;
}

/** Why the platform refused a name, as the person reads it: a name another agent has or went by says whose. */
function refusal(error: unknown): string {
    if (error instanceof NoClickError) return error.status === 409 ? `${error.message} Pick another name.` : error.message;
    return error instanceof Error ? error.message : 'It wasn’t renamed. Try again.';
}

/** Renames an agent; resolves to what's wrong, null once it has its new name (every page showing it reads it again,
 *  and other pages hear it from the agent's frame). */
export function useRenameAgent(): (agentId: string, name: string) => Promise<string | null> {
    const client = useWorkClient();
    return async (agentId, name) => {
        const problem = nameProblem(name);
        if (problem) return problem;
        try {
            await Agent.fromId(agentId, { client }).update({ name: name.trim() });
        } catch (error) {
            return refusal(error);
        }
        invalidateV1(AGENTS_KEY);
        invalidateV1(STATES_KEY);
        rereadAgent(agentId);
        return null;
    };
}

/** The name as a field: Enter saves, Esc cancels, what's wrong said under it. `current`: its name now (the same name
 *  again is a cancel); `draft` and `error`: what to open with (a /rename that was refused). `saveOnBlur` saves on
 *  leaving the field, as a name edited in place does; `submit` is how a button beside it saves. */
export function AgentNameField({
    current,
    draft = current,
    error: initialError = null,
    onSave,
    onCancel,
    saveOnBlur = false,
    submit,
    inputClassName,
    label = 'Its name',
}: {
    current: string;
    draft?: string;
    error?: string | null;
    onSave: (name: string) => Promise<string | null>;
    onCancel: () => void;
    saveOnBlur?: boolean;
    submit?: MutableRefObject<(() => void) | null>;
    inputClassName?: string;
    label?: string;
}) {
    const [value, setValue] = useState(draft);
    const [error, setError] = useState<string | null>(initialError);
    const [busy, setBusy] = useState(false);
    const input = useRef<HTMLInputElement>(null);
    const errorId = useId();
    useEffect(() => {
        input.current?.focus();
        input.current?.select();
    }, []);

    const save = async () => {
        if (busy) return;
        if (value.trim() === current) return onCancel();
        const problem = nameProblem(value);
        if (problem) return setError(problem);
        setBusy(true);
        const refused = await onSave(value.trim());
        setBusy(false);
        if (refused) {
            setError(refused);
            input.current?.focus();
        }
    };
    if (submit) submit.current = () => void save();

    return (
        <div className="min-w-0">
            <input
                ref={input}
                value={value}
                maxLength={MAX_AGENT_NAME + 20}
                aria-label={label}
                aria-invalid={!!error}
                aria-describedby={error ? errorId : undefined}
                enterKeyHint="done"
                autoComplete="off"
                spellCheck={false}
                disabled={busy}
                onChange={(e) => {
                    setValue(e.target.value);
                    setError(null);
                }}
                onKeyDown={(e) => {
                    if (e.key === 'Enter' && !e.nativeEvent.isComposing) {
                        e.preventDefault();
                        void save();
                    } else if (e.key === 'Escape') {
                        // Esc cancels the rename, never the panel or dialog around it.
                        e.preventDefault();
                        e.stopPropagation();
                        onCancel();
                    }
                }}
                onBlur={() => {
                    if (saveOnBlur && !error && !busy) void save();
                }}
                className={cn(
                    'w-full min-w-0 rounded-full bg-foreground/[0.04] px-4 outline-none ring-1 ring-inset ring-border transition-shadow focus:ring-foreground/30 disabled:opacity-60',
                    error && 'ring-red-500/60 focus:ring-red-500/70',
                    inputClassName ?? 'h-10 text-sm'
                )}
            />
            {error && (
                <p id={errorId} role="alert" className="mt-1.5 px-4 text-[12.5px] leading-snug text-red-600 dark:text-red-400">
                    {error}
                </p>
            )}
        </div>
    );
}

/** The agent's name as its profile heads it: click or tap it (or its pencil, there on a touch screen too) to rename it
 *  in place. A NoClick's name is just its name. */
export function EditableAgentName({ agent, name, className }: { agent: { id: string; noclick?: unknown }; name: string; className: string }) {
    const rename = useRenameAgent();
    const [editing, setEditing] = useState(false);
    if (!renamable(agent)) return <h2 className={className}>{name}</h2>;
    if (editing)
        return (
            <div className="mt-4">
                <AgentNameField
                    current={name}
                    saveOnBlur
                    label="Rename it"
                    inputClassName="h-11 text-[19px] font-semibold tracking-[-0.01em] max-md:text-[19px]"
                    onCancel={() => setEditing(false)}
                    onSave={async (next) => {
                        const refused = await rename(agent.id, next);
                        if (!refused) setEditing(false);
                        return refused;
                    }}
                />
            </div>
        );
    return (
        <h2 className={cn('group/name flex min-w-0 items-center gap-1.5', className)}>
            <button type="button" onClick={() => setEditing(true)} title="Rename" className="min-w-0 truncate rounded-lg text-left decoration-foreground/25 underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
                {name}
            </button>
            <button
                type="button"
                aria-label={`Rename ${name}`}
                onClick={() => setEditing(true)}
                className="grid h-7 w-7 shrink-0 place-items-center rounded-full text-muted-foreground opacity-0 transition-[opacity,background-color,color] hover:bg-foreground/[0.06] hover:text-foreground focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring group-hover/name:opacity-100 max-md:h-10 max-md:w-10 max-md:opacity-100 [@media(hover:none)]:opacity-100"
            >
                <Pencil className="h-3.5 w-3.5" strokeWidth={2} />
            </button>
        </h2>
    );
}

/** Rename from a menu: a small dialog holding the same field. */
export function useRenameDialog(): { ask: (agent: { id: string; name: string }) => void; dialog: ReactNode } {
    const [asking, setAsking] = useState<{ id: string; name: string } | null>(null);
    return { ask: setAsking, dialog: asking ? <RenameAgentDialog key={asking.id} agent={asking} onClose={() => setAsking(null)} /> : null };
}

function RenameAgentDialog({ agent, onClose }: { agent: { id: string; name: string }; onClose: () => void }) {
    const rename = useRenameAgent();
    const submit = useRef<(() => void) | null>(null);
    const save = async (name: string) => {
        const refused = await rename(agent.id, name);
        if (!refused) onClose();
        return refused;
    };
    return (
        <ShellDialog
            open
            onOpenChange={(o) => !o && onClose()}
            title={`Rename ${agent.name}`}
            description="Its old name keeps reaching it: mentions, messages and apps that use it find it under its new one."
            mark={<Pencil className="h-5 w-5" strokeWidth={1.75} />}
            testId="rename-agent"
            footer={
                <>
                    <button type="button" onClick={onClose} className={BUTTON_GHOST}>
                        Cancel
                    </button>
                    <button type="button" onClick={() => submit.current?.()} className={BUTTON_PRIMARY}>
                        Rename
                    </button>
                </>
            }
        >
            <div className="pb-1">
                <AgentNameField current={agent.name} label="New name" onSave={save} onCancel={onClose} submit={submit} />
            </div>
        </ShellDialog>
    );
}
