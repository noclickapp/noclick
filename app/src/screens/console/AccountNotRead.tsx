// What a console acting as a key shows when the API won't read the account to that key. Every page asks the account
// what it has (its plan, its balance, which features are on), so without it a page would say the account lacks what
// it only couldn't read. The console says what happened instead, and shows none of its pages.
import type { PermissionDenied } from 'noclick';

export function AccountNotRead({ error }: { error: PermissionDenied }) {
    return (
        <main role="alert" className="mx-auto flex min-h-screen max-w-xl flex-col justify-center gap-4 bg-background px-6 py-16 text-foreground">
            <h1 className="m-0 text-[20px] font-semibold tracking-tight">This API doesn&apos;t read the account to this key</h1>
            <p className="m-0 text-[14px] leading-relaxed text-muted-foreground">
                The console starts by reading the account (<code className="font-mono text-[13px] text-foreground">GET /v1/account</code>): its plan, its balance and what it has. The API this app&apos;s
                server called refused its key that read, so nothing here can be shown truthfully.
            </p>
            <p className="m-0 rounded-lg bg-foreground/[0.04] px-3 py-2.5 font-mono text-[12px] leading-relaxed text-foreground/80">{error.nextStep ? `${error.message} ${error.nextStep}` : error.message}</p>
            <p className="m-0 text-[14px] leading-relaxed text-muted-foreground">
                NoClick&apos;s API reads the account to one of the account&apos;s own secret keys, acting for the account itself. Check that the key this app&apos;s server holds is one (not a publishable
                key, and not one made to act for a single user), and that the API it calls is one that offers the read: an older one answers only the signed-in owner.
            </p>
        </main>
    );
}
