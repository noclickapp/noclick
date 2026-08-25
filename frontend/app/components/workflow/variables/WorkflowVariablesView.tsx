/**
 * WorkflowVariablesView — the workflow-variables editor, hosted in the
 * workflow Settings dialog (embedded mode): define variables (name, value,
 * description) that node configs reference as {{vars.name}} and the Setup tab
 * turns into guided steps while unfilled. Definitions persist in
 * workflows.settings.variable_definitions (shallow-merged on write, so the
 * graph autosave can never clobber them); runtime-written blob variables
 * overlay these values at execution time.
 */

import { useEffect, useMemo, useRef, useState } from 'react';
import type { Node } from '@xyflow/react';
import { Braces, Plus, Trash2, UserRound } from 'lucide-react';
import { cn } from '~/lib/utils';
import type { WorkflowVariableDefinition } from '~/hooks/useWorkflowVariables';

/** How many node config fields reference {{vars.name}} — the "safe to
    rename/delete?" signal. Substring scan over the flat config values. */
function usageCount(nodes: Node[], name: string): number {
    const needle = `vars.${name}`;
    let count = 0;
    for (const node of nodes) {
        const config = (node.data as { config?: Record<string, unknown> } | undefined)?.config;
        if (!config) continue;
        const scan = (v: unknown): void => {
            if (typeof v === 'string') {
                if (v.includes(needle)) count += 1;
            } else if (Array.isArray(v)) {
                v.forEach(scan);
            } else if (v && typeof v === 'object') {
                Object.values(v).forEach(scan);
            }
        };
        Object.values(config).forEach(scan);
    }
    return count;
}

export function WorkflowVariablesView({
    definitions,
    onChange,
    nodes,
    embedded = false,
}: {
    definitions: WorkflowVariableDefinition[];
    /** Persist the full definitions list (settings shallow-merge on write). */
    onChange: (definitions: WorkflowVariableDefinition[]) => void;
    nodes: Node[];
    /** Hosted inside another surface (the workflow Settings dialog): no page
        chrome, stacked fields, tighter rhythm. */
    embedded?: boolean;
}) {
    // Local draft so typing is instant; pushed up debounced. Row identity is
    // positional — names are editable, so they cannot be keys.
    const [draft, setDraft] = useState<WorkflowVariableDefinition[]>(definitions);
    const dirtyRef = useRef(false);
    useEffect(() => {
        // Adopt upstream changes only while we have nothing unsaved — a save
        // echo must not clobber keystrokes.
        if (!dirtyRef.current) setDraft(definitions);
    }, [definitions]);
    const pushTimer = useRef<number | null>(null);
    const push = (next: WorkflowVariableDefinition[]) => {
        setDraft(next);
        dirtyRef.current = true;
        if (pushTimer.current) window.clearTimeout(pushTimer.current);
        pushTimer.current = window.setTimeout(() => {
            dirtyRef.current = false;
            // The FULL draft goes up, unnamed rows included — persist-time
            // filtering is the dialog's Save's job. Filtering here bounced a
            // just-added empty row back down through the prop echo and made it
            // vanish mid-typing.
            onChange(next);
        }, 600);
    };
    // Unmount flush — leaving the tab must not lose the last keystrokes.
    const latestRef = useRef(draft);
    latestRef.current = draft;
    const onChangeRef = useRef(onChange);
    onChangeRef.current = onChange;
    useEffect(
        () => () => {
            if (pushTimer.current) {
                window.clearTimeout(pushTimer.current);
                onChangeRef.current(latestRef.current);
            }
        },
        []
    );

    const usages = useMemo(
        () => draft.map((d) => (d.name.trim() ? usageCount(nodes, d.name.trim()) : 0)),
        [draft, nodes]
    );

    const edit = (i: number, patch: Partial<WorkflowVariableDefinition>) =>
        push(draft.map((d, j) => (j === i ? { ...d, ...patch } : d)));
    const remove = (i: number) => push(draft.filter((_, j) => j !== i));
    const add = () => push([...draft, { name: '', value: '', description: '' }]);

    const FIELD =
        'w-full rounded-md border-0 bg-foreground/[0.045] px-2.5 text-[13px] outline-none transition-colors placeholder:text-foreground/25 focus:bg-foreground/[0.08]';

    const body = (
        <>
                {!embedded && (
                    <>
                        <div className="flex items-center gap-3">
                            <Braces className="h-5 w-5 text-foreground/50" />
                            <h1 className="m-0 text-[20px] font-semibold tracking-[-0.01em]">
                                Variables
                            </h1>
                        </div>
                        <p className="mb-0 mt-2 max-w-[60ch] text-[13px] leading-relaxed text-foreground/45">
                            Values any node config can reference as{' '}
                            <code className="rounded bg-foreground/[0.06] px-1 py-0.5 font-mono text-[12px]">
                                {'{{vars.name}}'}
                            </code>
                            . A variable left without a value becomes a step in Setup — declare
                            what a copy of this workflow needs, and setup will ask for it.
                        </p>
                    </>
                )}

                <div className={embedded ? 'space-y-1' : 'mt-8 space-y-1'}>
                    {draft.length === 0 && (
                        <button
                            onClick={add}
                            className="flex w-full flex-col items-center gap-2 rounded-xl border border-dashed border-foreground/15 px-4 py-6 text-center transition-colors hover:border-foreground/30 hover:bg-foreground/[0.02]"
                        >
                            <Braces className="h-5 w-5 text-foreground/30" />
                            <span className="text-[13px] font-medium text-foreground/70">
                                Define your first variable
                            </span>
                            <span className="max-w-[38ch] text-[12px] leading-relaxed text-foreground/40">
                                Reference it from any config as{' '}
                                <code className="rounded bg-foreground/[0.06] px-1 font-mono text-[11px]">
                                    {'{{vars.name}}'}
                                </code>
                                — mark it per-user and every copy of this workflow asks for its
                                own value in Setup.
                            </span>
                        </button>
                    )}
                    {draft.map((d, i) => (
                        <div key={i} className="rounded-lg px-1 py-1">
                            <div className="flex items-center gap-1.5">
                                <input
                                    value={d.name}
                                    onChange={(e) =>
                                        edit(i, { name: e.target.value.replace(/[^\w-]/g, '_') })
                                    }
                                    placeholder="name"
                                    className={cn(FIELD, 'h-7 w-[132px] shrink-0 font-mono text-[12px]')}
                                />
                                <input
                                    value={d.value ?? ''}
                                    onChange={(e) => edit(i, { value: e.target.value })}
                                    placeholder={d.per_user ? 'Asked in setup' : 'Value'}
                                    className={cn(FIELD, 'h-7 min-w-0 flex-1')}
                                />
                                <button
                                    onClick={() => edit(i, { per_user: !d.per_user })}
                                    title={
                                        d.per_user
                                            ? 'Asked per user: the value is cleared when this workflow is copied, so each new owner is asked in Setup'
                                            : 'Ask each new user — clears the value on copy so their Setup asks for it'
                                    }
                                    className={cn(
                                        'grid h-7 w-7 shrink-0 place-items-center rounded-md transition-colors',
                                        d.per_user
                                            ? 'bg-secondary text-foreground'
                                            : 'text-foreground/30 hover:bg-foreground/[0.05] hover:text-foreground/70'
                                    )}
                                >
                                    <UserRound className="h-3.5 w-3.5" />
                                </button>
                                <button
                                    onClick={() => remove(i)}
                                    title={
                                        usages[i]
                                            ? `Delete — referenced in ${usages[i]} field${usages[i] === 1 ? '' : 's'}`
                                            : 'Delete variable'
                                    }
                                    className="grid h-7 w-7 shrink-0 place-items-center rounded-md text-foreground/30 transition-colors hover:bg-foreground/[0.05] hover:text-red-400"
                                >
                                    <Trash2 className="h-3.5 w-3.5" />
                                </button>
                            </div>
                            <input
                                value={d.description ?? ''}
                                onChange={(e) => edit(i, { description: e.target.value })}
                                placeholder="Description — the question Setup asks"
                                className="mt-1 h-6 w-full rounded-md bg-transparent px-2.5 text-[12px] text-foreground/60 outline-none transition-colors placeholder:text-foreground/25 focus:bg-foreground/[0.04]"
                            />
                        </div>
                    ))}
                </div>

                <button
                    onClick={add}
                    className="mt-4 inline-flex items-center gap-1.5 rounded-lg border border-foreground/15 px-3 py-2 text-[13px] font-medium transition-colors hover:bg-foreground/[0.04]"
                >
                    <Plus className="h-3.5 w-3.5" />
                    New variable
                </button>
        </>
    );

    if (embedded) return <div>{body}</div>;
    return (
        <div className="min-h-0 flex-1 overflow-y-auto bg-background text-foreground">
            <div className="mx-auto w-full max-w-[760px] px-6 py-10">{body}</div>
        </div>
    );
}
