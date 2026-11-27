// Save as template, from a space's menu: the space written into a new repository of yours as a template (its channels,
// its agents and their instructions, the skills, memories and automations they use, its app's code), never its
// messages, data, people or accounts. A dry run says what goes in before anything is made; making it public is a
// switch, checked for secrets first as an app's code is, and once public anyone can clone it from its address.
import { useEffect, useState, type FormEvent } from 'react';
import { Copy, LayoutTemplate, Loader2 } from 'lucide-react';
import { toast } from 'sonner';
import { ApprovalRequired, Workspace, type JsonObject, type NoClick, type PublicCode, type SpaceTemplate } from 'noclick';
import { ShellDialog } from '@/ui/ShellDialog';
import { BUTTON_GHOST, BUTTON_PRIMARY, BUTTON_SECONDARY } from '@/ui/buttons';
import { FIELD, FIELD_LABEL } from '@/ui/fields';
import { Switch } from '@/ui/switch';
import { cn } from '@/ui/utils';
import { errorText } from '@/screens/console/pages/resources/shared';
import { useWork } from './context';
import type { WorkSpace } from './spaces';

const plural = (n: number, one: string, many: string) => (n === 1 ? `${/^[aeiou]/.test(one) ? 'an' : 'a'} ${one}` : `${n} ${many}`);
const names = (value: unknown): string[] => (Array.isArray(value) ? value.filter((v): v is string => typeof v === 'string') : []);

/** What a template holds, in a line: "2 channels, 3 agents and their instructions, a skill and its app's code". */
export function containsLine(contains: JsonObject): string {
    const parts = [
        ['channels', 'channel', 'channels'],
        ['agents', 'agent', 'agents'],
        ['skills', 'skill', 'skills'],
        ['memories', 'memory', 'memories'],
        ['automations', 'automation', 'automations'],
        ['stores', 'data store', 'data stores'],
    ].flatMap(([key, one, many]) => {
        const n = names(contains[key]).length;
        if (!n) return [];
        return [key === 'agents' ? `${plural(n, one, many)} and ${n === 1 ? 'its' : 'their'} instructions` : plural(n, one, many)];
    });
    if (contains.app === true) parts.push('its app’s code');
    return parts.length > 1 ? `${parts.slice(0, -1).join(', ')} and ${parts[parts.length - 1]}` : (parts[0] ?? 'Nothing yet');
}

/** What it asks whoever adds it for, in a line, or null when it asks nothing. */
function asksLine(asks: JsonObject): string | null {
    const accounts = (Array.isArray(asks.connections) ? asks.connections : []).map((c) => String((c as JsonObject).integration ?? ''));
    const secrets = (Array.isArray(asks.secrets) ? asks.secrets : []).map((s) => String((s as JsonObject).name ?? ''));
    const said = [accounts.length ? `to connect ${accounts.join(', ')}` : '', secrets.length ? `for ${secrets.length === 1 ? 'a secret' : `${secrets.length} secrets`} (${secrets.join(', ')})` : ''].filter(Boolean);
    return said.length ? `It asks whoever adds it ${said.join(' and ')}.` : null;
}

export function SaveTemplateDialog({ space, client, onClose }: { space: WorkSpace; client: NoClick; onClose: () => void }) {
    const { openPage } = useWork();
    const [dry, setDry] = useState<SpaceTemplate | null>(null);
    const [problem, setProblem] = useState<string | null>(null);
    const [repoName, setRepoName] = useState('');
    const [description, setDescription] = useState('');
    const [goPublic, setGoPublic] = useState(false);
    const [busy, setBusy] = useState(false);
    const [saved, setSaved] = useState<SpaceTemplate | null>(null);
    const [published, setPublished] = useState<PublicCode | null>(null);
    const [publicNote, setPublicNote] = useState<string | null>(null);
    const workspace = () => Workspace.fromId(space.workspaceId ?? '', { client, user: null });

    useEffect(() => {
        let live = true;
        workspace()
            .saveAsTemplate({ dryRun: true })
            .then(
                (found) => {
                    if (!live) return;
                    setDry(found);
                    setRepoName(found.repoName);
                },
                (e: unknown) => live && setProblem(errorText(e))
            );
        return () => {
            live = false;
        };
        // eslint-disable-next-line react-hooks/exhaustive-deps -- read once as the dialog opens
    }, [space.workspaceId, client]);

    const submit = async (e: FormEvent) => {
        e.preventDefault();
        if (busy || !dry || !repoName.trim()) return;
        setBusy(true);
        setProblem(null);
        try {
            const made = await workspace().saveAsTemplate({ repoName: repoName.trim(), description: description.trim() || undefined });
            setSaved(made);
            if (goPublic && made.repo) {
                try {
                    setPublished(await made.repo.makePublic());
                } catch (err) {
                    setPublicNote(err instanceof ApprovalRequired ? 'Making it public waits for the account’s owner: NoClick sent them a link saying what becomes public.' : `It’s saved, but private: ${errorText(err)}`);
                }
            }
        } catch (err) {
            setProblem(errorText(err));
        } finally {
            setBusy(false);
        }
    };

    const link = published?.originUrl ?? null;
    const copy = (text: string) => void navigator.clipboard?.writeText(text).then(() => toast('Copied'));
    const leftOut = dry?.leftOut ?? [];
    return (
        <ShellDialog
            open
            onOpenChange={(open) => !open && !busy && onClose()}
            size="md"
            mark={<LayoutTemplate className="h-5 w-5" strokeWidth={1.75} />}
            title={`Save ${space.name} as a template`}
            description="Others get its setup, never its messages, data or your accounts."
            onSubmit={saved ? undefined : (e) => void submit(e)}
            testId="save-template"
            footer={
                saved ? (
                    <>
                        {saved.repo && openPage && (
                            <button type="button" className={BUTTON_GHOST} onClick={() => openPage('resources', { kind: 'repos', resource: saved.repo?.id ?? null })}>
                                Open its code
                            </button>
                        )}
                        <button type="button" className={BUTTON_PRIMARY} onClick={onClose}>
                            Done
                        </button>
                    </>
                ) : (
                    <>
                        <button type="button" className={BUTTON_GHOST} onClick={onClose} disabled={busy}>
                            Cancel
                        </button>
                        <button type="submit" className={BUTTON_PRIMARY} disabled={!dry || busy || !repoName.trim()}>
                            {busy && <Loader2 className="h-4 w-4 animate-spin" />}
                            Save template
                        </button>
                    </>
                )
            }
        >
            {saved ? (
                <div data-testid="template-saved" className="flex flex-col gap-3 pb-1 text-[13.5px] text-muted-foreground">
                    <p className="m-0 text-foreground">
                        Saved as the repository <span className="font-medium">{saved.repoName}</span>. {link ? 'Anyone can clone it from its address:' : 'Only you see it until you make it public.'}
                    </p>
                    {link && (
                        <div className="flex items-center gap-2 rounded-2xl bg-foreground/[0.05] py-1.5 pl-3.5 pr-1.5">
                            <code className="min-w-0 flex-1 truncate font-mono text-[12.5px] text-foreground" data-testid="template-link">
                                {link}
                            </code>
                            <button type="button" aria-label="Copy the address" className={BUTTON_SECONDARY} onClick={() => copy(link)}>
                                <Copy className="h-4 w-4" />
                            </button>
                        </div>
                    )}
                    {publicNote && (
                        <p role="status" className="m-0">
                            {publicNote}
                        </p>
                    )}
                </div>
            ) : (
                <div className="flex flex-col gap-4 pb-1">
                    <section aria-label="What goes in" className="text-[13.5px]">
                        <p className={FIELD_LABEL}>What goes in</p>
                        {dry ? (
                            <>
                                <p className="m-0 text-foreground" data-testid="template-contains">
                                    {containsLine(dry.contains)}.
                                </p>
                                {asksLine(dry.asks) && <p className="m-0 mt-1 text-muted-foreground">{asksLine(dry.asks)}</p>}
                            </>
                        ) : problem ? null : (
                            <span aria-busy className="block h-5 w-72 animate-pulse rounded bg-foreground/[0.06]" />
                        )}
                    </section>
                    {dry && (
                        <section aria-label="What never does" className="text-[13.5px] text-muted-foreground">
                            <p className={FIELD_LABEL}>Never in it</p>
                            <p className="m-0" data-testid="template-never">
                                {dry.never.map((n, i) => (i === 0 ? n[0].toUpperCase() + n.slice(1) : n)).join('; ')}.
                            </p>
                            {leftOut.length > 0 && (
                                <details className="mt-1.5">
                                    <summary className="cursor-pointer">{leftOut.length === 1 ? '1 more thing stays behind' : `${leftOut.length} more things stay behind`}</summary>
                                    <ul className="mb-0 mt-1 list-disc pl-5">
                                        {leftOut.map((item) => (
                                            <li key={item.what}>
                                                <span className="text-foreground">{item.what}</span>: {item.why}
                                            </li>
                                        ))}
                                    </ul>
                                </details>
                            )}
                        </section>
                    )}
                    <label className="block">
                        <span className={FIELD_LABEL}>Kept as</span>
                        <input value={repoName} onChange={(e) => setRepoName(e.target.value)} maxLength={64} className={FIELD} aria-describedby="template-kept" />
                        <span id="template-kept" className="mt-1 block text-[12.5px] text-muted-foreground">
                            A repository of yours: edit it like any code.
                        </span>
                    </label>
                    <label className="block">
                        <span className={FIELD_LABEL}>What it does</span>
                        <input value={description} onChange={(e) => setDescription(e.target.value)} maxLength={500} placeholder="Plans, writes and posts for your brand" className={FIELD} />
                    </label>
                    <div className="flex items-center justify-between gap-4">
                        <div className="min-w-0 text-[13.5px]">
                            <p className="m-0 text-foreground">Make it public</p>
                            <p className="m-0 text-[12.5px] text-muted-foreground">Checked for secrets first, as an app’s code is. A copy someone added can’t be taken back.</p>
                        </div>
                        <Switch checked={goPublic} onCheckedChange={setGoPublic} aria-label="Make it public" />
                    </div>
                    <p className={cn('m-0 text-[12.5px]', problem ? 'text-red-600 dark:text-red-400' : 'hidden')} role={problem ? 'alert' : undefined}>
                        {problem}
                    </p>
                </div>
            )}
        </ShellDialog>
    );
}
