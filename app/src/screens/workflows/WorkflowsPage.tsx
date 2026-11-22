// The account's workflows: the ones the key can open, under the folders the account keeps them in, each a way into
// its page, and a new one made by name. Where a workflow's page is comes from whoever draws this page (`onOpen`).
import { useMemo, useState, type FormEvent } from 'react';
import { ChevronRight, Folder, Loader2, Plus, Workflow as WorkflowGlyph } from 'lucide-react';
import { toast } from 'sonner';
import { relativeShort } from '@/lib/formatters';
import { useClient } from '@/sdk/client';
import { errorText } from '@/screens/console/lib/errorText';
import { BUTTON_PRIMARY, BUTTON_SECONDARY } from '@/ui/buttons';
import { FIELD } from '@/ui/fields';
import { PageFrame } from '@/ui/PageFrame';
import { cn } from '@/ui/utils';
import { createWorkflow, useWorkflowList, type FolderRow, type WorkflowRow } from './reads';

export interface WorkflowsPageProps {
    /** Opens a workflow's page. */
    onOpen: (workflowId: string) => void;
}

/** The folders in the order a tree reads: each under the one it's in, by name. */
function inTreeOrder(folders: readonly FolderRow[]): FolderRow[] {
    const under = new Map<string | null, FolderRow[]>();
    for (const folder of folders) under.set(folder.parentId, [...(under.get(folder.parentId) ?? []), folder]);
    const walk = (parent: string | null): FolderRow[] =>
        (under.get(parent) ?? []).sort((a, b) => a.name.localeCompare(b.name)).flatMap((folder) => [folder, ...walk(folder.id)]);
    return walk(null);
}

function Row({ workflow, onOpen, indent }: { workflow: WorkflowRow; onOpen: (id: string) => void; indent: number }) {
    return (
        <li>
            <button
                type="button"
                onClick={() => onOpen(workflow.id)}
                data-testid={`workflow-row-${workflow.id}`}
                className="group flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left transition-colors hover:bg-foreground/[0.04]"
                style={{ paddingLeft: 12 + indent * 20 }}
            >
                <WorkflowGlyph className="h-4 w-4 shrink-0 text-muted-foreground" />
                <span className="min-w-0 flex-1">
                    <span className="block truncate text-[14px] font-medium text-foreground">{workflow.name}</span>
                    {workflow.description && <span className="block truncate text-[13px] text-muted-foreground">{workflow.description}</span>}
                </span>
                {workflow.paused && <span className="shrink-0 rounded-full bg-secondary px-2 py-0.5 text-[11px] font-medium text-muted-foreground">Paused</span>}
                {workflow.access === 'viewer' && <span className="shrink-0 rounded-full bg-secondary px-2 py-0.5 text-[11px] font-medium text-muted-foreground">View only</span>}
                {workflow.updatedAt && <span className="shrink-0 text-[12px] tabular-nums text-muted-foreground">{relativeShort(workflow.updatedAt.toISOString())}</span>}
                <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground/60 transition-transform group-hover:translate-x-0.5" />
            </button>
        </li>
    );
}

export function WorkflowsPage({ onOpen }: WorkflowsPageProps) {
    const client = useClient();
    const { list, error, reload } = useWorkflowList();
    const [naming, setNaming] = useState(false);
    const [name, setName] = useState('');
    const [making, setMaking] = useState(false);

    const folders = useMemo(() => inTreeOrder(list?.folders ?? []), [list]);
    const inFolder = useMemo(() => {
        const known = new Set(folders.map((f) => f.id));
        const by = new Map<string | null, WorkflowRow[]>();
        // One in a folder that isn't listed (another account's) reads at the top.
        for (const workflow of list?.workflows ?? []) {
            const at = workflow.folderId && known.has(workflow.folderId) ? workflow.folderId : null;
            by.set(at, [...(by.get(at) ?? []), workflow]);
        }
        return by;
    }, [list, folders]);

    const make = async (event: FormEvent) => {
        event.preventDefault();
        const called = name.trim();
        if (!called || making) return;
        setMaking(true);
        try {
            const id = await createWorkflow(client, called);
            setName('');
            setNaming(false);
            void reload();
            onOpen(id);
        } catch (cause) {
            toast.error(errorText(cause));
        } finally {
            setMaking(false);
        }
    };

    return (
        <PageFrame
            title="Automations"
            description="Workflows your account runs: each a trigger, the steps it takes and the agents that work in it."
            actions={
                <button type="button" className={BUTTON_PRIMARY} onClick={() => setNaming(true)}>
                    <Plus className="h-4 w-4" /> New workflow
                </button>
            }
        >
            {naming && (
                <form onSubmit={make} className="mb-6 flex flex-wrap items-center gap-2" aria-label="New workflow">
                    <input autoFocus value={name} onChange={(e) => setName(e.target.value)} placeholder="Name it" aria-label="The workflow’s name" className={cn(FIELD, 'max-w-[320px] flex-1')} />
                    <button type="submit" className={BUTTON_PRIMARY} disabled={!name.trim() || making}>
                        {making && <Loader2 className="h-4 w-4 animate-spin" />} Create
                    </button>
                    <button type="button" className={BUTTON_SECONDARY} onClick={() => setNaming(false)}>
                        Cancel
                    </button>
                </form>
            )}
            {error && (
                <p role="alert" className="text-[14px] text-red-600 dark:text-red-400">
                    Your workflows couldn’t be read: {error}
                </p>
            )}
            {!error && !list && <p className="text-[14px] text-muted-foreground">Reading your workflows…</p>}
            {list && list.workflows.length === 0 && <p className="text-[14px] text-muted-foreground">No workflows yet. Make one, then add its steps on its canvas or ask NoClick to build it.</p>}
            {list && list.workflows.length > 0 && (
                <div className="space-y-5" data-testid="workflow-list">
                    {(inFolder.get(null) ?? []).length > 0 && (
                        <ul className="space-y-0.5">
                            {(inFolder.get(null) ?? []).map((workflow) => (
                                <Row key={workflow.id} workflow={workflow} onOpen={onOpen} indent={0} />
                            ))}
                        </ul>
                    )}
                    {folders.map((folder) => (
                        <section key={folder.id} aria-label={folder.name}>
                            <h2 className="flex items-center gap-2 px-3 pb-1 text-[13px] font-medium text-muted-foreground" style={{ paddingLeft: 12 + folder.depth * 20 }}>
                                <Folder className="h-3.5 w-3.5" /> {folder.name}
                            </h2>
                            <ul className="space-y-0.5">
                                {(inFolder.get(folder.id) ?? []).map((workflow) => (
                                    <Row key={workflow.id} workflow={workflow} onOpen={onOpen} indent={folder.depth + 1} />
                                ))}
                            </ul>
                        </section>
                    ))}
                </div>
            )}
        </PageFrame>
    );
}
