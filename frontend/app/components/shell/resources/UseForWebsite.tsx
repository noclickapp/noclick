// Putting one of the account's websites on a domain: which website, then the
// registered platform serves it there (platform.tsx). A dialog on a domain's
// page, and the one optional step after buying a domain.
import { useState, type FormEvent } from 'react';
import { toast } from 'sonner';
import { Loader2 } from 'lucide-react';
import { BUTTON_GHOST, BUTTON_PRIMARY, BUTTON_SECONDARY } from '../buttons';
import { ShellDialog } from '../ShellDialog';
import { usePlatformResources } from './platform';
import { ChoiceList } from './ui';

function useServeWebsite(domain: string) {
    const platform = usePlatformResources();
    const apps = platform?.items.apps ?? [];
    // The only website is picked for you.
    const preset = apps.length === 1 ? apps[0].id : null;
    const [appId, setAppId] = useState<string | null>(preset);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const app = apps.find((a) => a.id === appId);
    const reset = () => {
        setAppId(preset);
        setError(null);
    };
    /** True once it's on its way there. */
    const serve = async (e: FormEvent): Promise<boolean> => {
        e.preventDefault();
        if (!platform || !app || busy) return false;
        setBusy(true);
        setError(null);
        try {
            await platform.serveApp(app.id, domain);
            toast.success(`Putting ${app.title} on ${domain}`, { description: 'It shows there once everything’s set up, usually within a few minutes.' });
            return true;
        } catch (err) {
            setError(err instanceof Error ? err.message : String(err));
            return false;
        } finally {
            setBusy(false);
        }
    };
    const choices = (
        <>
            <ChoiceList label="Websites" choices={apps.map((a) => ({ value: a.id, title: a.title, detail: a.subtitle }))} value={appId} onChange={setAppId} />
            {error && (
                <p role="alert" className="mt-3 text-[13.5px] text-red-600 dark:text-red-400">
                    {error}
                </p>
            )}
        </>
    );
    const submit = (
        <button type="submit" disabled={!app || busy} className={BUTTON_PRIMARY}>
            {busy && <Loader2 className="h-4 w-4 animate-spin" />}
            Use {domain}
        </button>
    );
    return { serve, choices, submit, reset };
}

/** On a domain's page: pick the website it shows. */
export function UseForWebsiteDialog({ domain, open, onOpenChange }: { domain: string; open: boolean; onOpenChange: (open: boolean) => void }) {
    const { serve, choices, submit, reset } = useServeWebsite(domain);
    // Every way out goes through here, so it opens again with nothing left from last time.
    const close = () => {
        reset();
        onOpenChange(false);
    };
    return (
        <ShellDialog
            open={open}
            onOpenChange={(next) => (next ? onOpenChange(true) : close())}
            size="md"
            title={`Use ${domain} for a website`}
            description={`Pick the website people see at ${domain}.`}
            onSubmit={async (e) => {
                if (await serve(e)) close();
            }}
            footer={
                <>
                    <button type="button" className={BUTTON_GHOST} onClick={close}>
                        Cancel
                    </button>
                    {submit}
                </>
            }
        >
            {choices}
        </ShellDialog>
    );
}

/** After buying `domain`: the same choice, which can wait for later. */
export function UseBoughtDomain({ domain, onDone }: { domain: string; onDone: () => void }) {
    const { serve, choices, submit } = useServeWebsite(domain);
    return (
        <form
            className="max-w-2xl"
            aria-label={`Use ${domain} for a website`}
            onSubmit={async (e) => {
                if (await serve(e)) onDone();
            }}
        >
            {choices}
            <div className="mt-8 flex flex-wrap items-center gap-2">
                {submit}
                <button type="button" onClick={onDone} className={BUTTON_SECONDARY}>
                    Not now
                </button>
            </div>
        </form>
    );
}
