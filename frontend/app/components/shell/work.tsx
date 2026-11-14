// Work: where your agents and the people you work with talk, in spaces as in Slack. It runs on the hosted platform's
// API, so a deployment registers the page (lazily, from its bootstrap, so nothing loads until Work opens); without one
// the page says Work isn't available here, as the open edition does.
import { Suspense, type ComponentType, type ReactNode } from 'react';
import { BriefcaseBusiness } from 'lucide-react';
import type { AccountMenuUser } from '~/components/nav/AccountMenu';
import { HAIRLINE } from '~/components/dashboard/surfaces';
import { BUTTON_PRIMARY } from '~/components/shell/buttons';
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

/** A sentence in the middle of the page: why there's nothing to show, and the one thing to do about it. `mark` stands
 *  in for the briefcase over it; `children`, for a surface whose way on isn't one button (a menu of people). */
export function WorkNotice({ title, body, action, mark, children, testId = 'work-notice' }: { title: string; body: string; action?: { label: string; onClick: () => void }; mark?: ReactNode; children?: ReactNode; testId?: string }) {
    return (
        <div className="grid h-full w-full place-items-center px-6" data-testid={testId}>
            <div className="flex max-w-sm flex-col items-center text-center">
                {mark ?? (
                    <span className="grid h-12 w-12 place-items-center rounded-2xl bg-foreground/[0.05] ring-1 ring-inset ring-foreground/[0.06]">
                        <BriefcaseBusiness className="h-6 w-6 text-foreground/70" strokeWidth={1.75} />
                    </span>
                )}
                <h1 className={cn('mt-4', PAGE_TITLE, 'text-[28px]')}>{title}</h1>
                <p className="mt-1.5 text-balance text-[14.5px] leading-relaxed text-muted-foreground">{body}</p>
                {action && (
                    <button type="button" onClick={action.onClick} className={cn('mt-5', BUTTON_PRIMARY)}>
                        {action.label}
                    </button>
                )}
                {children && <div className="mt-5 flex flex-wrap justify-center gap-2">{children}</div>}
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
