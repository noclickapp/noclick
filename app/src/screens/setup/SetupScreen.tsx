// What every page shows while one of the app's settings is missing or unusable: which ones, and how to fix each.
// Names only: the server never sends a setting's value here. A setting the host gives the app itself (`given`: the
// key NoClick gives a copy deployed on NoClick, once the account's owner approves it) is said as that, with nothing
// to set.
import { PAGE_TITLE } from '@/ui/titles';

export interface SetupProblem {
    name: string;
    problem: string;
    fix: string;
    given?: boolean;
}

/** What the gate throws (a 503) for the root's error boundary to draw as this screen. */
export interface SetupData {
    setup: SetupProblem[];
}

export function isSetupData(value: unknown): value is SetupData {
    return typeof value === 'object' && value !== null && Array.isArray((value as SetupData).setup);
}

export function SetupScreen({ problems }: { problems: SetupProblem[] }) {
    // Nothing here is the reader's to set when the host gives every setting named: the page says where each stands.
    const waiting = problems.every((problem) => problem.given);
    return (
        <main className="mx-auto flex min-h-screen max-w-xl flex-col justify-center gap-6 px-6 py-16">
            <div className="flex flex-col gap-2">
                <h1 className={PAGE_TITLE}>{waiting ? 'This app’s key isn’t ready' : 'Finish setting up this app'}</h1>
                <p className="text-[14px] text-muted-foreground">
                    {waiting
                        ? 'NoClick gives this app its key to your account itself. Nobody pastes one.'
                        : 'It reads its settings from environment variables, and these are missing or need changing.'}
                </p>
            </div>
            <ul className="flex flex-col divide-y divide-border dark:divide-foreground/[0.08]">
                {problems.map((problem) => (
                    <li key={problem.name} className="flex flex-col gap-1 py-3.5 text-[14px]">
                        <p>
                            <code className="font-mono text-[13px] font-medium text-foreground">{problem.name}</code>{' '}
                            <span className="text-foreground/85">{problem.problem}</span>
                        </p>
                        <p className="text-muted-foreground">{problem.fix}</p>
                    </li>
                ))}
            </ul>
            {!waiting && (
                <p className="text-[14px] text-muted-foreground">
                    Set them where the app runs (your host’s settings; on your own machine, see <code className="font-mono">.env.example</code>),
                    then restart the app.
                </p>
            )}
        </main>
    );
}
