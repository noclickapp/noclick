// Connecting a domain the person already owns: enter the name, then the records to
// add where its DNS is hosted (each copyable, each with its state), one-click setup
// where that host supports it, and Verify.
import { useReducer, useState } from 'react';
import { ExternalLink } from 'lucide-react';
import { toast } from 'sonner';
import { cn } from '@/ui/utils';
import { Domain } from 'noclick';
import { useConsole } from '@/screens/console/hooks/useConsole';
import { invalidateV1 } from '@/sdk/useV1';
import { ConsoleButton, consoleButtonClass } from '../../ui/Button';
import { ConsoleDialog } from '../../ui/ConsoleDialog';
import { ErrorPanel } from '../../ui/ErrorPanel';
import { StatusPill } from '../../ui/StatusPill';
import { UserField } from '../../ui/UserField';
import { INPUT, LabeledInput } from './shared';
import { DnsRecordList, domainLook } from './DomainsParts';

/** The records a connected domain needs, the one-click setup, and a check now. */
export function ConnectedRecords({ domain, onChanged }: { domain: Domain; onChanged: () => void }) {
    const [checking, setChecking] = useState(false);
    const [error, setError] = useState<unknown>(undefined);
    const verify = async () => {
        setChecking(true);
        setError(undefined);
        try {
            await domain.verify();
            onChanged();
            invalidateV1('domains?');
            toast(domain.status === 'active' ? `${domain.name} is active` : `Checked ${domain.name}: some records aren't there yet`);
        } catch (e) {
            setError(e);
        } finally {
            setChecking(false);
        }
    };
    const bare = domain.records.some((r) => !r.required && r.name === '@');
    return (
        <div className="flex flex-col gap-3">
            <p className="m-0 text-[13px] text-muted-foreground">
                {`Add these where ${domain.name}'s DNS is hosted. NoClick checks every few minutes; Verify checks now.`}
                {bare && ` www.${domain.name} is the primary address. The bare name needs CNAME flattening (an ALIAS or ANAME record), or a forward to www.`}
            </p>
            <DnsRecordList records={domain.records} label="Records to add" />
            <div className="flex flex-wrap items-center gap-2">
                {domain.setupUrl && (
                    <a href={domain.setupUrl} target="_blank" rel="noreferrer" className={consoleButtonClass('primary', 'sm')}>
                        Set up automatically <ExternalLink className="h-3 w-3" />
                    </a>
                )}
                <ConsoleButton size="sm" disabled={checking} onClick={() => void verify()}>
                    {checking ? 'Checking…' : 'Verify'}
                </ConsoleButton>
                {domain.setupUrl && <span className="text-[12px] text-muted-foreground">Its DNS host adds them in one click.</span>}
            </div>
            {error !== undefined && <ErrorPanel error={error} />}
        </div>
    );
}

export function ConnectDomainDialog({ defaultUser, onOpenDomain }: { defaultUser: string | null; onOpenDomain: (id: string) => void }) {
    const { client, now } = useConsole();
    const [open, setOpen] = useState(false);
    const [user, setUser] = useState<string | null>(defaultUser);
    const [name, setName] = useState('');
    const [wildcard, setWildcard] = useState(false);
    const [domain, setDomain] = useState<Domain | null>(null);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<unknown>(undefined);
    const [, rerender] = useReducer((n: number) => n + 1, 0);
    const connect = async () => {
        setBusy(true);
        setError(undefined);
        try {
            setDomain(await Domain.connect(name.trim().toLowerCase(), { client, user, wildcard: wildcard || undefined }));
            invalidateV1('domains?');
            invalidateV1('account');
        } catch (e) {
            setError(e);
        } finally {
            setBusy(false);
        }
    };
    return (
        <>
            <ConsoleButton
                onClick={() => {
                    setUser(defaultUser);
                    setName('');
                    setWildcard(false);
                    setDomain(null);
                    setError(undefined);
                    setOpen(true);
                }}
            >
                Connect a domain
            </ConsoleButton>
            <ConsoleDialog
                open={open}
                onOpenChange={setOpen}
                size={domain ? 'lg' : 'md'}
                title={domain ? <span className="font-mono">{domain.name}</span> : 'Connect a domain'}
                description={domain ? undefined : 'A domain the person already owns. It stays with its registrar; you add a few DNS records.'}
                footer={
                    domain ? (
                        <>
                            <ConsoleButton
                                variant="ghost"
                                onClick={() => {
                                    setOpen(false);
                                    onOpenDomain(domain.id);
                                }}
                            >
                                View domain
                            </ConsoleButton>
                            <ConsoleButton variant="primary" onClick={() => setOpen(false)}>
                                Done
                            </ConsoleButton>
                        </>
                    ) : (
                        <ConsoleButton variant="primary" disabled={busy || !name.trim()} onClick={() => void connect()}>
                            {busy ? 'Connecting…' : 'Connect'}
                        </ConsoleButton>
                    )
                }
            >
                {domain ? (
                    <div className="flex flex-col gap-3">
                        <StatusPill look={domainLook(domain, now())} className="self-start" />
                        <ConnectedRecords domain={domain} onChanged={rerender} />
                    </div>
                ) : (
                    <form
                        className="flex flex-col gap-3"
                        onSubmit={(e) => {
                            e.preventDefault();
                            if (name.trim()) void connect();
                        }}
                    >
                        <UserField value={user} onChange={setUser} />
                        <LabeledInput label="Domain" id="connect-name">
                            <input id="connect-name" className={cn(INPUT, 'font-mono')} value={name} onChange={(e) => setName(e.target.value)} placeholder="acme.com or book.acme.com" />
                        </LabeledInput>
                        <p className="m-0 text-[12px] text-muted-foreground">
                            A subdomain needs one record. A bare domain serves at www, and the bare name follows with CNAME flattening or a forward.
                        </p>
                        <label className="flex items-start gap-2 text-[13px]">
                            <input type="checkbox" className="mt-0.5" checked={wildcard} onChange={(e) => setWildcard(e.target.checked)} />
                            <span>
                                Every subdomain too
                                <span className="block text-[12px] text-muted-foreground">
                                    Adds the <span className="font-mono">*.</span> records, so any subdomain can serve an app or send email without its own records.
                                </span>
                            </span>
                        </label>
                        {error !== undefined && <ErrorPanel error={error} />}
                    </form>
                )}
            </ConsoleDialog>
        </>
    );
}
