// Adding a workspace: name it (its tile shows as you type) and give it a logo
// if you have one. You land in it, ready to start its first channel.
import { useEffect, useRef, useState, type FormEvent } from 'react';
import { ImagePlus } from 'lucide-react';
import { ShellDialog } from '~/components/shell/ShellDialog';
import { BUTTON_GHOST, BUTTON_PRIMARY } from '~/components/shell/buttons';
import { FIELD, FIELD_LABEL } from '~/components/shell/fields';
import { cn } from '~/lib/utils';
import { initialsFor } from './model';
import { WorkspaceTile } from './workspaces';

const TEXT_BUTTON = 'font-medium text-foreground/80 underline decoration-foreground/25 underline-offset-[3px] transition-colors hover:text-foreground hover:decoration-foreground/60';

/** A logo the platform keeps: JPEG, PNG, WebP or GIF, up to 2 MB. */
const LOGO_TYPES = ['image/jpeg', 'image/png', 'image/webp', 'image/gif'];
const LOGO_MAX_BYTES = 2 * 1024 * 1024;

export function AddWorkspaceDialog({ open, onOpenChange, onCreate }: { open: boolean; onOpenChange: (open: boolean) => void; onCreate: (name: string, logo?: File) => Promise<void> }) {
    const [name, setName] = useState('');
    const [logo, setLogo] = useState<File>();
    const [logoUrl, setLogoUrl] = useState<string>();
    const [problem, setProblem] = useState<string | null>(null);
    const [busy, setBusy] = useState(false);
    const logoInput = useRef<HTMLInputElement>(null);
    const ready = !!name.trim() && !busy;

    useEffect(() => () => void (logoUrl && URL.revokeObjectURL(logoUrl)), [logoUrl]);

    const pickLogo = (file?: File) => {
        if (!file) return;
        if (!LOGO_TYPES.includes(file.type)) return setProblem('A logo is a JPEG, PNG, WebP or GIF.');
        if (file.size > LOGO_MAX_BYTES) return setProblem('A logo is at most 2 MB.');
        setProblem(null);
        setLogo(file);
        setLogoUrl(URL.createObjectURL(file));
    };
    const removeLogo = () => {
        setLogo(undefined);
        setLogoUrl(undefined);
    };
    const reset = () => {
        setName('');
        removeLogo();
        setProblem(null);
    };
    const close = (next: boolean) => {
        if (busy) return;
        onOpenChange(next);
        if (!next) reset();
    };

    const submit = async (e: FormEvent) => {
        e.preventDefault();
        if (!ready) return;
        setBusy(true);
        setProblem(null);
        try {
            await onCreate(name.trim(), logo);
            onOpenChange(false);
            reset();
        } catch (err) {
            setProblem(err instanceof Error ? err.message : 'Couldn’t create the workspace.');
        } finally {
            setBusy(false);
        }
    };

    return (
        <ShellDialog
            open={open}
            onOpenChange={close}
            title="Add a workspace"
            description="A place for a team and its agents to talk."
            markTile={false}
            mark={
                <button
                    type="button"
                    onClick={() => logoInput.current?.click()}
                    aria-label={logo ? 'Change the logo' : 'Upload a logo'}
                    className="group relative shrink-0 rounded-[14px] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-card dark:focus-visible:ring-offset-sunken"
                >
                    <WorkspaceTile workspace={{ name: name.trim() || 'New workspace', logoUrl }} size={48} className={cn('transition-opacity', !name.trim() && !logoUrl && 'opacity-40')} />
                    <span className="absolute -bottom-1 -right-1 grid h-5 w-5 place-items-center rounded-full bg-card text-muted-foreground shadow-sm ring-1 ring-border transition-colors group-hover:text-foreground dark:bg-sunken dark:ring-foreground/[0.12]">
                        <ImagePlus className="h-3 w-3" strokeWidth={2} />
                    </span>
                </button>
            }
            onSubmit={(e) => void submit(e)}
            testId="add-workspace-dialog"
            footer={
                <>
                    <button type="button" onClick={() => close(false)} className={BUTTON_GHOST}>
                        Cancel
                    </button>
                    <button type="submit" disabled={!ready} className={BUTTON_PRIMARY}>
                        {busy ? 'Creating…' : 'Create workspace'}
                    </button>
                </>
            }
        >
            <input
                ref={logoInput}
                type="file"
                accept={LOGO_TYPES.join(',')}
                className="hidden"
                data-testid="workspace-logo-input"
                onChange={(e) => {
                    pickLogo(e.target.files?.[0]);
                    // The same file picked twice should fire again.
                    e.target.value = '';
                }}
            />
            <label className="block pt-2">
                <span className={FIELD_LABEL}>Name</span>
                <input
                    // eslint-disable-next-line jsx-a11y/no-autofocus -- the dialog opens to type a name
                    autoFocus
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    placeholder="Harbor Health, Lumen, your club…"
                    maxLength={100}
                    className={FIELD}
                />
            </label>
            <p className={cn('mt-1.5 text-[12.5px]', problem ? 'text-red-600 dark:text-red-400' : 'text-muted-foreground')} role={problem ? 'alert' : undefined}>
                {problem ??
                    (logo ? (
                        <>
                            Logo added.{' '}
                            <button type="button" onClick={removeLogo} className={TEXT_BUTTON}>
                                Remove it
                            </button>
                        </>
                    ) : (
                        <>
                            {name.trim() ? `Shows as “${initialsFor(name)}”` : 'Shows its initials'} until you{' '}
                            <button type="button" onClick={() => logoInput.current?.click()} className={TEXT_BUTTON}>
                                add a logo
                            </button>
                            .
                        </>
                    ))}
            </p>
        </ShellDialog>
    );
}
