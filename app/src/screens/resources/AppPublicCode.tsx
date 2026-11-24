// Whether an app's code is public, on its page under Resources (and its repo's): anyone clones a public app from its
// own address and deploys their own copy from that address alone. Making it public first shows what would become
// public and what the check for secrets found (a dry run), then asks; making it private is one confirm, and says that
// copies already made stay. A copy of someone's public app says where it came from.
import { useEffect, useState } from 'react';
import { Copy, Globe, Loader2, Lock } from 'lucide-react';
import { toast } from 'sonner';
import { BUTTON_GHOST, BUTTON_PRIMARY, BUTTON_SECONDARY } from '@/ui/buttons';
import { ShellDialog } from '@/ui/ShellDialog';
import { usePlatformResources } from './platform';
import { ConfirmAction, Section, Surface } from './ui';
import { ROW } from './parts';
import { errorText } from '@/screens/console/pages/resources/shared';
import { useOwnerOnly } from '@/screens/console/ownerOnly';
import { ApprovalRequired, type Project, type PublicCode } from 'noclick';

function shortSha(sha: string | null): string {
    return sha ? sha.slice(0, 7) : '';
}

function licence(code: PublicCode): string {
    if (!code.license) return 'No LICENSE file: anyone may read and clone it, but nobody is granted the right to reuse it.';
    return code.license === 'other' ? 'Its LICENSE file names a licence NoClick doesn’t recognise.' : `Licensed ${code.license}.`;
}

/** The dialog that makes an app's code public: what would go public and what scanning found, then the ask. */
export function MakePublicDialog({ project, open, onOpenChange }: { project: Project; open: boolean; onOpenChange: (open: boolean) => void }) {
    const platform = usePlatformResources();
    const [preview, setPreview] = useState<PublicCode | null>(null);
    const [error, setError] = useState<unknown>(undefined);
    const [busy, setBusy] = useState(false);
    const [held, setHeld] = useState(false);
    useEffect(() => {
        if (!open) return;
        setPreview(null);
        setError(undefined);
        setHeld(false);
        let live = true;
        project.makePublic({ dryRun: true }).then(
            (found) => live && setPreview(found),
            (e: unknown) => live && setError(e),
        );
        return () => {
            live = false;
        };
    }, [open, project]);
    const publish = async () => {
        setBusy(true);
        setError(undefined);
        try {
            const made = await project.makePublic();
            platform?.refresh();
            toast(`${project.name}'s code is public at ${made.cloneUrl ?? project.url}`);
            onOpenChange(false);
        } catch (e) {
            if (e instanceof ApprovalRequired) setHeld(true);
            else setError(e);
        } finally {
            setBusy(false);
        }
    };
    const blocked = !!preview && preview.wouldPublish === false;
    return (
        <ShellDialog
            open={open}
            onOpenChange={onOpenChange}
            title="Make its code public"
            description={`Anyone will be able to clone ${project.name} from ${project.url} and deploy their own copy.`}
            footer={
                held ? (
                    <button type="button" className={BUTTON_PRIMARY} onClick={() => onOpenChange(false)}>
                        Done
                    </button>
                ) : (
                    <>
                        <button type="button" className={BUTTON_GHOST} onClick={() => onOpenChange(false)}>
                            Cancel
                        </button>
                        <button type="button" className={BUTTON_PRIMARY} disabled={!preview || blocked || busy} onClick={() => void publish()}>
                            {busy && <Loader2 className="h-4 w-4 animate-spin" />}
                            Make public
                        </button>
                    </>
                )
            }
        >
            <div data-testid="make-public" className="flex flex-col gap-3 text-[13.5px] text-muted-foreground">
                {held ? (
                    <p role="status" className="m-0 text-foreground">
                        It waits for the account’s owner: NoClick sent them a link saying what becomes public. It’s public once they say yes.
                    </p>
                ) : preview ? (
                    <>
                        <p className="m-0 text-foreground">{preview.summary}</p>
                        {preview.findings.length > 0 && (
                            <div role="alert">
                                <p className="m-0 text-red-600 dark:text-red-400">Nothing goes public while these look like secrets:</p>
                                <ul className="mt-1.5 list-disc pl-5">
                                    {preview.findings.map((f) => (
                                        <li key={f.path}>
                                            <span className="font-mono text-foreground">{f.path}</span>: {f.why}
                                        </li>
                                    ))}
                                </ul>
                                <p className="mb-0 mt-1.5">Take them out of the repo (keep a value as one of the app’s secrets), deploy, then try again.</p>
                            </div>
                        )}
                    </>
                ) : error === undefined ? (
                    <span aria-busy className="h-5 w-64 animate-pulse rounded bg-foreground/[0.06]" />
                ) : null}
                {error !== undefined && (
                    <p role="alert" className="m-0 text-red-600 dark:text-red-400">
                        {errorText(error)}
                    </p>
                )}
            </div>
        </ShellDialog>
    );
}

export function AppPublicCode({ project }: { project: Project }) {
    const platform = usePlatformResources();
    const ownerOnly = useOwnerOnly();
    const [making, setMaking] = useState(false);
    const code = project.public;
    const forked = project.forkedFrom;
    if (project.published) return null; // a page NoClick publishes has no code of its own
    const makePrivate = async () => {
        const done = await project.makePrivate();
        platform?.refresh();
        toast(done.summary ?? 'Its code is private');
    };
    const copy = (text: string) => {
        void navigator.clipboard.writeText(text).then(() => toast('Copied'));
    };
    const canPublish = ownerOnly('publishCode');
    return (
        <Section
            title="Code"
            meta={code?.public ? 'Public' : code?.blocked ? 'Taken down' : 'Private'}
            action={
                code?.public ? (
                    <ConfirmAction quiet label="Make private" confirm="Stop clones" icon={Lock} onConfirm={makePrivate} />
                ) : !code?.blocked && canPublish ? (
                    <button type="button" className={BUTTON_SECONDARY} onClick={() => setMaking(true)}>
                        <Globe className="h-4 w-4" />
                        Make public
                    </button>
                ) : undefined
            }
        >
            <div data-testid="app-public-code" className="flex max-w-[72ch] flex-col gap-2 text-[13.5px] text-muted-foreground">
                {forked && (
                    <p className="m-0">
                        Copied from <span className="text-foreground">{forked.address}</span>, which its owner made public.
                    </p>
                )}
                {code?.public ? (
                    <>
                        <Surface>
                            <div className={ROW}>
                                <code className="min-w-0 flex-1 truncate font-mono text-[13px] text-foreground">git clone {code.cloneUrl}</code>
                                <button type="button" aria-label="Copy" className={BUTTON_GHOST} onClick={() => copy(`git clone ${code.cloneUrl}`)}>
                                    <Copy className="h-4 w-4" />
                                </button>
                            </div>
                        </Surface>
                        <p className="m-0">
                            Anyone can clone it, and deploy their own copy from {code.cloneUrl}. Public at commit {shortSha(code.sourceCommit)};{' '}
                            {code.forks === 1 ? '1 copy' : `${code.forks} copies`} deployed from it. {licence(code)}
                        </p>
                        {canPublish && (
                            <p className="m-0">
                                <button type="button" className="font-medium text-foreground underline underline-offset-4" onClick={() => setMaking(true)}>
                                    Publish its newest code
                                </button>
                            </p>
                        )}
                    </>
                ) : code?.blocked ? (
                    <p role="status" className="m-0 text-foreground">
                        NoClick took its public code down: {code.raw.blocked_reason as string}
                    </p>
                ) : (
                    <p className="m-0">Only you see its code. Make it public and anyone can clone it from {project.url}; a copy someone cloned can’t be taken back.</p>
                )}
            </div>
            <MakePublicDialog project={project} open={making} onOpenChange={setMaking} />
        </Section>
    );
}
