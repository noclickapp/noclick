// Adding a domain to a website from its page in Resources: one of the domains
// of whoever holds the website (the account's for its own, a user's for one of
// that user's), or any other name, which is connected and then shows the records
// to add where its DNS is hosted. It adds as the developer console's dialog does
// (appDomains).
import { useId, useState, type FormEvent } from 'react';
import { toast } from 'sonner';
import { ExternalLink, Loader2 } from 'lucide-react';
import { BUTTON_GHOST, BUTTON_PRIMARY } from '@/ui/buttons';
import { FIELD, FIELD_LABEL, QUIET_LINK } from '@/ui/fields';
import { ShellDialog } from '@/ui/ShellDialog';
import { DnsRecords } from './ResourceDetail';
import { ChoiceList } from './ui';
import { domainName, isDomainName, useAddAppDomain } from '@/screens/console/pages/resources/appDomains';
import { sourceLabel } from '@/screens/console/pages/resources/DomainsParts';
import type { Domain, Project } from 'noclick';
import { domainRecords, domainState, freeForWebsite, servingRefusal } from './items';

const OTHER = 'other';

/** A connected name waits on records its owner adds where its DNS is hosted. */
const needsRecords = (d: Domain) => d.source === 'connected' && d.status === 'pending_dns' && d.records.length > 0;

export function AddDomainDialog({ project, domains, open, onOpenChange }: { project: Project; domains: readonly Domain[]; open: boolean; onOpenChange: (open: boolean) => void }) {
    const fieldId = useId();
    // A domain's own name serves only an app of the same scope: the account's, or the same user's.
    const free = domains.filter((d) => d.userId === project.userId && freeForWebsite(d));
    const [choice, setChoice] = useState<string | null>(null);
    const [typed, setTyped] = useState('');
    const { busy, error, added, add, reset } = useAddAppDomain(project, 'resources:');
    const typing = choice === OTHER || free.length === 0;
    const name = typing ? domainName(typed) : choice;
    const valid = !!name && isDomainName(name);

    const close = (next: boolean) => {
        if (!next) {
            setChoice(null);
            setTyped('');
            reset();
        }
        onOpenChange(next);
    };
    const submit = async (e: FormEvent) => {
        e.preventDefault();
        if (!valid || busy) return;
        const domain = await add(name);
        if (!domain || needsRecords(domain)) return;
        toast.success(`Adding ${name}`, { description: `${project.name} shows there once it’s set up, usually within a few minutes.` });
        close(false);
    };

    if (added && needsRecords(added)) {
        return (
            <ShellDialog
                open={open}
                onOpenChange={close}
                size="lg"
                title={`Connect ${added.name}`}
                description={`Add them where ${added.name}’s DNS is hosted, usually where you bought it. Your site goes live a few minutes after NoClick finds them.`}
                footer={
                    <button type="button" className={BUTTON_PRIMARY} onClick={() => close(false)}>
                        Done
                    </button>
                }
            >
                {added.setupUrl && (
                    <a href={added.setupUrl} target="_blank" rel="noopener noreferrer" className={QUIET_LINK}>
                        Set them up for me
                        <ExternalLink className="h-3.5 w-3.5" />
                    </a>
                )}
                <DnsRecords records={domainRecords(added)} title="Records to add" className="mt-2" />
            </ShellDialog>
        );
    }

    return (
        <ShellDialog
            open={open}
            onOpenChange={close}
            size="md"
            title="Add a domain"
            description={`Show ${project.name} at an address of your own.`}
            onSubmit={submit}
            footer={
                <>
                    <button type="button" className={BUTTON_GHOST} onClick={() => close(false)}>
                        Cancel
                    </button>
                    <button type="submit" disabled={!valid || busy} className={BUTTON_PRIMARY}>
                        {busy && <Loader2 className="h-4 w-4 animate-spin" />}
                        Add domain
                    </button>
                </>
            }
        >
            {free.length > 0 && (
                <ChoiceList
                    label="Your domains"
                    choices={[
                        ...free.map((d) => ({ value: d.name, title: d.name, detail: [sourceLabel(d), domainState(d).words].join(' · ') })),
                        { value: OTHER, title: 'Another domain', detail: 'One you own somewhere else, or a name under one of yours' },
                    ]}
                    value={choice}
                    onChange={setChoice}
                />
            )}
            {typing && (
                <div className={free.length > 0 ? 'mt-3' : undefined}>
                    <label htmlFor={fieldId} className={FIELD_LABEL}>
                        Domain
                    </label>
                    <input
                        id={fieldId}
                        className={FIELD}
                        value={typed}
                        onChange={(e) => setTyped(e.target.value)}
                        placeholder="bakery.com or shop.bakery.com"
                        autoComplete="off"
                        autoCapitalize="none"
                        autoCorrect="off"
                        spellCheck={false}
                    />
                    <p className="mt-1.5 text-[12.5px] text-muted-foreground">If it’s registered somewhere else, you’ll get the records to add there.</p>
                </div>
            )}
            {error !== undefined && (
                <p role="alert" className="mt-3 text-[13.5px] text-red-600 dark:text-red-400">
                    {servingRefusal(error)}
                </p>
            )}
        </ShellDialog>
    );
}
