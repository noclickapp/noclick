// Work: where your agents and the people you work with talk, in spaces as in Slack. It runs on the hosted platform's
// API, so a deployment registers the page (lazily, from its bootstrap, so nothing loads until Work opens); without one
// the page says Work isn't available here, as the open edition does.
import { Suspense, type ComponentType } from 'react';
import { BriefcaseBusiness } from 'lucide-react';
import type { AccountMenuUser } from '~/components/nav/AccountMenu';
import { HAIRLINE } from '~/components/dashboard/surfaces';
import { PAGE_TITLE } from '~/components/shell/titles';
import { cn } from '~/lib/utils';

export interface WorkPageProps {
    user: AccountMenuUser;
}

let Page: ComponentType<WorkPageProps> | null = null;

/** The deployment's Work page. */
export function registerWorkPage(page: ComponentType<WorkPageProps>): void {
    Page = page;
}

export function hasWorkPage(): boolean {
    return Page !== null;
}

/** A sentence in the middle of the page: why there's nothing to show, and the one thing to do about it. */
export function WorkNotice({ title, body, action }: { title: string; body: string; action?: { label: string; onClick: () => void } }) {
    return (
        <div className="grid h-full w-full place-items-center px-6" data-testid="work-notice">
            <div className="max-w-sm text-center">
                <span className="mx-auto grid h-12 w-12 place-items-center rounded-2xl bg-foreground/[0.05] ring-1 ring-inset ring-foreground/[0.06]">
                    <BriefcaseBusiness className="h-6 w-6 text-foreground/70" strokeWidth={1.75} />
                </span>
                <h1 className={cn('mt-4', PAGE_TITLE, 'text-[28px]')}>{title}</h1>
                <p className="mt-1.5 text-[14.5px] leading-relaxed text-muted-foreground">{body}</p>
                {action && (
                    <button
                        type="button"
                        onClick={action.onClick}
                        className="mt-5 inline-flex h-9 items-center rounded-full bg-primary px-4 text-[13.5px] font-medium text-primary-foreground transition-opacity hover:opacity-90"
                    >
                        {action.label}
                    </button>
                )}
            </div>
        </div>
    );
}

/** The page's rails and list as grey shapes, while it loads. */
export function WorkLoading() {
    return (
        <div className="flex h-full" aria-busy data-testid="work-loading">
            <div className={cn('hidden w-[68px] shrink-0 border-r lg:block', HAIRLINE)} />
            <div className={cn('hidden w-[84px] shrink-0 border-r lg:block', HAIRLINE)} />
            <div className={cn('w-full space-y-2 p-4 lg:w-[280px] lg:border-r', HAIRLINE)}>
                {[0, 1, 2, 3].map((i) => (
                    <div key={i} className="h-7 animate-pulse rounded-lg bg-foreground/[0.04]" />
                ))}
            </div>
        </div>
    );
}

export function WorkPage({ user }: WorkPageProps) {
    if (!Page) return <WorkNotice title="Work isn't available here" body="Work runs on NoClick's hosted platform, which this instance doesn't include." />;
    return (
        <Suspense fallback={<WorkLoading />}>
            <Page user={user} />
        </Suspense>
    );
}
