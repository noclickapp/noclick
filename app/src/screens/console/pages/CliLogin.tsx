// Signing the CLI in: `noclick login` prints a code and this page's link; the
// signed-in owner compares the code and the machine, then approves (the CLI's
// next poll gets an API key named after its machine) or denies.
import { useState } from 'react';
import { CliLogin as SignIn } from 'noclick';
import { Link } from 'react-router';
import { HAIRLINE } from '@/ui/primitives';
import { Input } from '@/ui/input';
import { cn } from '@/ui/utils';
import { useSlot } from '@/slots';
import { TERMS } from '../slots';
import { useConsole, useConsoleHref } from '@/screens/console/hooks/useConsole';
import { invalidateV1, useV1 } from '@/sdk/useV1';
import { useSearchParam } from '@/screens/console/hooks/useQueryState';
import { ConsoleButton, consoleButtonClass } from '../ui/Button';
import { ErrorPanel } from '../ui/ErrorPanel';
import { Fact, Facts } from '../ui/Detail';
import { PageHeader } from '../ui/PageHeader';
import { TimeCell } from '../ui/TimeCell';
import { FormField, INPUT } from './Users';

/** A sign-in `noclick login` started, as `GET /v1/cli/logins/{code}` reads it. */
export interface CliLogin {
    object: 'cli_login';
    user_code: string;
    client: string;
    hostname: string;
    ip: string | null;
    key_name: string;
    status: 'pending' | 'approved' | 'denied';
    created_at: string;
    expires_at: string;
}

function CodeForm({ onCode }: { onCode: (code: string) => void }) {
    const [typed, setTyped] = useState('');
    return (
        <form
            className="flex max-w-sm flex-col gap-3"
            onSubmit={(e) => {
                e.preventDefault();
                if (typed.trim()) onCode(typed.trim().toUpperCase());
            }}
        >
            <FormField label="Code" htmlFor="cli-code" hint="The code your terminal printed after noclick login.">
                <Input id="cli-code" className={cn(INPUT, 'font-mono uppercase tracking-wider')} value={typed} onChange={(e) => setTyped(e.target.value)} placeholder="WDJB-MJHT" autoComplete="off" />
            </FormField>
            <div>
                <ConsoleButton type="submit" variant="primary" disabled={!typed.trim()}>
                    Continue
                </ConsoleButton>
            </div>
        </form>
    );
}

function Answered({ login, onAnother }: { login: CliLogin; onAnother: () => void }) {
    const href = useConsoleHref();
    const approved = login.status === 'approved';
    return (
        <div role="status" className={cn('max-w-xl rounded-xl border bg-card p-5', HAIRLINE)}>
            <p className="m-0 text-[14px] font-medium text-foreground">{approved ? 'Approved.' : 'Denied.'}</p>
            <p className="m-0 mt-1 text-[13px] text-muted-foreground">
                {approved ? (
                    <>
                        Your terminal on <span className="font-mono text-foreground">{login.hostname}</span> signs in within a few seconds, with the key{' '}
                        <span className="text-foreground">{login.key_name}</span>. You can close this page.
                    </>
                ) : (
                    <>The terminal on {login.hostname} stops waiting and gets no key.</>
                )}
            </p>
            <div className="mt-4 flex items-center gap-2">
                {approved && (
                    <Link to={href('keys')} className={consoleButtonClass('soft')}>
                        See it in API keys
                    </Link>
                )}
                <ConsoleButton variant="ghost" onClick={onAnother}>
                    Another code
                </ConsoleButton>
            </div>
        </div>
    );
}

function Pending({ code, onAnother }: { code: string; onAnother: () => void }) {
    const Terms = useSlot(TERMS);
    const { client } = useConsole();
    const login = useV1(`cli_login:${code}`, () => SignIn.get(code, { client }));
    const [answered, setAnswered] = useState<CliLogin | null>(null);
    const [failure, setFailure] = useState<unknown>(undefined);
    const [busy, setBusy] = useState(false);

    if (answered) return <Answered login={answered} onAnother={onAnother} />;
    if (login.error !== undefined) {
        return (
            <div className="flex max-w-xl flex-col gap-3">
                <ErrorPanel error={login.error} onRetry={() => void login.refresh()} />
                <div>
                    <ConsoleButton variant="ghost" onClick={onAnother}>
                        Type another code
                    </ConsoleButton>
                </div>
            </div>
        );
    }
    if (!login.data) return <div aria-busy className="h-48 max-w-xl animate-pulse rounded-xl bg-foreground/[0.03]" />;

    const signIn = login.data;
    const view = signIn.raw as unknown as CliLogin;
    const answer = async (approved: boolean) => {
        setBusy(true);
        setFailure(undefined);
        try {
            setAnswered((await signIn.answer(approved)).raw as unknown as CliLogin);
            if (approved) invalidateV1('keys');
        } catch (error) {
            setFailure(error);
        } finally {
            setBusy(false);
        }
    };
    return (
        <div className={cn('flex max-w-xl flex-col gap-4 rounded-xl border bg-card p-5', HAIRLINE)}>
            <div>
                <p className="m-0 text-[13px] text-muted-foreground">Check that your terminal shows this code</p>
                <p className="m-0 mt-1 font-mono text-[26px] font-semibold tracking-[0.14em] text-foreground">{view.user_code}</p>
            </div>
            <Facts>
                <Fact label="Machine">
                    <span className="font-mono">{view.hostname}</span>
                </Fact>
                <Fact label="Started">
                    <TimeCell value={view.created_at} />
                    {view.ip && <span className="text-muted-foreground"> from {view.ip}</span>}
                </Fact>
                <Fact label="Key it gets">
                    {view.key_name}: full access, without the scopes that read secrets. Revoke it any time in API keys, or with noclick logout.
                </Fact>
            </Facts>
            <p className="m-0 text-[13px] text-muted-foreground">
                Approve only a sign-in you started yourself, just now. Anyone you approve can build and spend on this account.
            </p>
            <Terms action="approving" />
            {failure !== undefined && <ErrorPanel error={failure} className="bg-transparent" />}
            <div className="flex items-center gap-2">
                <ConsoleButton variant="primary" onClick={() => void answer(true)} disabled={busy}>
                    Approve
                </ConsoleButton>
                <ConsoleButton variant="ghost" onClick={() => void answer(false)} disabled={busy}>
                    Deny
                </ConsoleButton>
            </div>
        </div>
    );
}

export default function CliLogin() {
    const [code, setCode] = useSearchParam('code');
    return (
        <>
            <PageHeader section="cli" />
            {code ? <Pending key={code} code={code} onAnother={() => setCode(null)} /> : <CodeForm onCode={(typed) => setCode(typed)} />}
        </>
    );
}
