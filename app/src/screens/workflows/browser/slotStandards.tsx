// What stands in the Automations page's slots (../slots.ts) when no host fills them.
import { useEffect, useState, type FormEvent } from 'react';
import { GitFork, Lock } from 'lucide-react';
import { useNavigate } from 'react-router';
import { ShellDialog } from '@/ui/ShellDialog';
import { BUTTON_GHOST, BUTTON_PRIMARY } from '@/ui/buttons';
import { FIELD, FIELD_LABEL } from '@/ui/fields';
import { workflowRoute } from '../routes';
import { useWorkflowsHost } from './context';
import { browserWrites, failureOf } from './workflowBrowserStore';

/** An open workflow, as the page hands it to whatever draws it. */
export interface WorkflowCanvasProps {
    workflowId: string;
    workflowTitle: string;
    onBack: () => void;
    onDelete: (workflowId: string) => void;
    onTitleChange: (title: string) => void;
    /** The name the server holds, shown, never written back. */
    onTitleShown: (title: string) => void;
    onNavigateToWorkflow: (workflowId: string) => void;
}

/** The standard canvas: the workflow's own page, where its host opens it, else in this app. */
export function OpenOnItsPage({ workflowId }: WorkflowCanvasProps) {
    const navigate = useNavigate();
    const { openWorkflow } = useWorkflowsHost();
    useEffect(() => {
        if (openWorkflow) openWorkflow(workflowId);
        else navigate(workflowRoute(workflowId), { replace: true });
    }, [navigate, openWorkflow, workflowId]);
    return null;
}

export interface ShareDialogProps {
    isOpen: boolean;
    onOpenChange: (open: boolean) => void;
    resource: { id: string; name: string } | null;
    resourceType: 'workflow' | 'workflow_folder';
}

export interface ForkDialogProps {
    isOpen: boolean;
    onOpenChange: (open: boolean) => void;
    resource: { id: string; name: string } | null;
    resourceType: 'workflow';
    /** The workspace the page lists (`personal`, or `org_<id>`): where the copy is made. */
    scopeId: string;
    onForkSuccess?: () => void;
}

/** The standard copy: a workflow copied by name into the workspace the page lists, through the platform API. */
export function ForkStandard({ isOpen, onOpenChange, resource, scopeId, onForkSuccess }: ForkDialogProps) {
    const [name, setName] = useState('');
    const [making, setMaking] = useState(false);
    const [error, setError] = useState<string | null>(null);
    useEffect(() => {
        if (isOpen && resource) {
            setName(`${resource.name} (copy)`);
            setError(null);
        }
    }, [isOpen, resource]);
    const submit = async (e: FormEvent) => {
        e.preventDefault();
        if (!resource || !name.trim() || making) return;
        setMaking(true);
        try {
            await browserWrites.forkWorkflow(scopeId, resource.id, name.trim());
            onOpenChange(false);
            onForkSuccess?.();
        } catch (err) {
            setError(failureOf(err));
        } finally {
            setMaking(false);
        }
    };
    return (
        <ShellDialog
            open={isOpen}
            onOpenChange={onOpenChange}
            mark={<GitFork className="h-5 w-5" strokeWidth={1.75} />}
            title="Fork automation"
            description="An independent copy you own."
            onSubmit={submit}
            footer={
                <>
                    <button type="button" onClick={() => onOpenChange(false)} disabled={making} className={BUTTON_GHOST}>
                        Cancel
                    </button>
                    <button type="submit" disabled={!name.trim() || making} className={BUTTON_PRIMARY}>
                        {making ? 'Forking…' : 'Fork'}
                    </button>
                </>
            }
        >
            <label className="block space-y-2 pt-2">
                <span className={FIELD_LABEL}>Name</span>
                <input value={name} onChange={(e) => setName(e.target.value)} className={FIELD} autoFocus />
            </label>
            {error && <p className="mt-3 text-[13px] text-red-600 dark:text-red-400">{error}</p>}
        </ShellDialog>
    );
}

export interface PlanNoticeProps {
    /** How many automations shared with the account its plan's limit hides. */
    hidden: number;
    /** The plan's name as the API names it (`free`). */
    tier: string;
}

/** The standard notice: the limit in plain words. */
export function NoPlanNotice({ hidden }: PlanNoticeProps) {
    return (
        <div className="pb-4">
            <div className="flex items-center gap-2.5 rounded-xl border border-amber-500/25 bg-amber-500/[0.06] px-4 py-3">
                <Lock className="h-4 w-4 flex-shrink-0 text-amber-600 dark:text-amber-400" />
                <p className="text-[13.5px] text-foreground/90">
                    The plan&rsquo;s automation limit hides {hidden} automation{hidden === 1 ? '' : 's'}. Delete automations to
                    see {hidden === 1 ? 'it' : 'them'}.
                </p>
            </div>
        </div>
    );
}

export interface RefusalProps {
    /** The refusal's words; null while there's none. */
    message: string | null;
    onClose: () => void;
}

/** The standard refusal: the API's words in a dialog. */
export function RefusalStandard({ message, onClose }: RefusalProps) {
    return (
        <ShellDialog
            open={message !== null}
            onOpenChange={(open) => !open && onClose()}
            title="Your plan's limit"
            description={message ?? undefined}
            footer={
                <button type="button" onClick={onClose} className={BUTTON_PRIMARY}>
                    OK
                </button>
            }
        />
    );
}
