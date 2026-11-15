// Setting an agent up without leaving the thread: the apps it needs, each with the one thing that connects it, the
// accounts a turn asks for on one card (a row each, connected from its row), and the agent itself drawn on a canvas
// while it's built.
import { useRef, type ReactNode } from 'react';
import { verdictState, verdictSummary } from '~/components/credential/ConnectionVerdict';
import type { ProvideRequestProblem } from '~/components/credential/CredentialProvideFlow';
import type { ScaffoldBlob } from '~/lib/agentScaffold';
import { cn } from '~/lib/utils';
import type { CredentialTestConnectionResponse } from '~/types/socket-events.generated';
import { ThinkingOrb } from '~/components/shared/ThinkingOrb';
import { Canvas } from './canvas';
import { FreshCheck, ProgressMotion, Swap } from './motion';
import { InlineCard, listOf, LiveDot, PILL_QUIET, Receipt, Row, Rows, Status } from './primitives';

export interface AppRow {
    key: string;
    mark: ReactNode;
    label: string;
    /** Why it's needed, before; what only a connected account could show, after. */
    detail?: ReactNode;
    /** Its state or the one action that connects it. */
    aside: ReactNode;
}

/** The accounts an agent needs, one row each. */
export function ConnectAppsCard({ title, meta, apps }: { title: ReactNode; meta?: ReactNode; apps: AppRow[] }) {
    return (
        <InlineCard title={title} meta={meta}>
            <Rows className="-mb-1">
                {apps.map((app) => (
                    <Row key={app.key} lead={app.mark} title={app.label} detail={app.detail} aside={app.aside} />
                ))}
            </Rows>
        </InlineCard>
    );
}

/** An account that's in: who it is, and what the connect-time check said when it just ran here. */
export interface ConnectedAccount {
    name: string;
    account?: string;
    verification?: CredentialTestConnectionResponse | null;
}

/** A key nothing could check is saved, never shown as working. */
const savedOnly = (verification?: CredentialTestConnectionResponse | null) => !!verification && verdictState(verification) === 'unverified';

/** What the check proved (their customers, their channels), else the account itself. */
const accountLine = ({ account, verification }: ConnectedAccount) => verdictSummary(verification) ?? account;

/** The accounts a turn asks to connect, as one card: a row each (its mark, its name, how it connects and the one button
 *  that does it), counted as they land. Once every one is in, the card folds to `ConnectedSummary`. */
export function ConnectAccountsCard({ total, done, meta, children }: { total: number; done: number; meta?: ReactNode; children: ReactNode }) {
    return (
        <InlineCard
            title={total === 1 ? 'Connect an account' : `Connect ${total} accounts`}
            meta={meta}
            aside={total > 1 && <span className="text-[12.5px] tabular-nums text-muted-foreground">{`${done} of ${total} done`}</span>}
        >
            <div data-testid="coordinator-connect">
                <Rows className="-mb-1">{children}</Rows>
            </div>
        </InlineCard>
    );
}

/** What a test finds an account's row by. */
export const connectRowId = (name: string) => `connect-row:${name}`;

/** An account's row once it's in: a check, and who it is. */
export function ConnectedRow({ mark, connected }: { mark: ReactNode; connected: ConnectedAccount }) {
    const saved = savedOnly(connected.verification);
    return (
        <Row
            testId={connectRowId(connected.name)}
            lead={mark}
            title={connected.name}
            detail={saved ? 'Saved, not verified yet' : 'Connected'}
            aside={
                !saved && (
                    <Status state="done">
                        <span className="max-w-[200px] truncate">{accountLine(connected)}</span>
                    </Status>
                )
            }
        />
    );
}

/** Every account in, in one line. */
export function ConnectedSummary({ accounts }: { accounts: ConnectedAccount[] }) {
    if (accounts.length === 1) return <ConnectedReceipt {...accounts[0]} />;
    const saved = accounts.filter((a) => savedOnly(a.verification)).map((a) => a.name);
    const connected = accounts.filter((a) => !savedOnly(a.verification)).map((a) => a.name);
    if (!connected.length) return <Receipt tone="info">{listOf(saved)} saved, not verified yet · the first run will tell</Receipt>;
    return (
        <Receipt>
            {listOf(connected)} {connected.length === 1 ? 'is' : 'are'} connected{saved.length ? ` · ${listOf(saved)} saved, not verified yet` : ''}
        </Receipt>
    );
}

/** A connected account in one line: what the connect-time check proved when it just ran here, else the account itself. */
export function ConnectedReceipt({ name, account, verification }: ConnectedAccount) {
    if (savedOnly(verification)) return <Receipt tone="info">{name} saved, not verified yet · the first run will tell</Receipt>;
    const line = accountLine({ name, account, verification });
    return (
        <Receipt>
            {name} connected{line ? ` · ${line}` : ''}
        </Receipt>
    );
}

/** Why a request can no longer be connected here: ended for a reason of its own (`note`), or what to do about it. */
export function unavailableLine(name: string, problem: ProvideRequestProblem, note?: string): string {
    if (note) return note;
    if (problem === 'failed' || problem === 'unreachable') return `Couldn’t load the way to connect ${name}`;
    const why =
        problem === 'too_many'
            ? `Too many tries to connect ${name}`
            : problem === 'cancelled'
              ? `The request to connect ${name} was cancelled`
              : problem === 'not_found'
                ? `A newer request to connect ${name} replaced this one`
                : `${name} wasn’t connected in time`;
    return `${why} · ask NoClick again`;
}

/** A request that just couldn't be read, which another try may load. */
export const retriesRead = (problem: ProvideRequestProblem, note?: string) => !note && (problem === 'failed' || problem === 'unreachable');

/** A request that can no longer be connected here, in one line, with another try when it just couldn't be read. */
export function ConnectUnavailable({ name, problem, note, onRetry }: { name: string; problem: ProvideRequestProblem; note?: string; onRetry: () => void }) {
    return (
        <Receipt
            tone="info"
            action={
                retriesRead(problem, note) && (
                    <button type="button" className={cn(PILL_QUIET, 'h-7')} onClick={onRetry}>
                        Try again
                    </button>
                )
            }
        >
            {unavailableLine(name, problem, note)}
        </Receipt>
    );
}

export interface BuildPart {
    type: string;
    label: string;
}

/** `started`: handed to the builder, with no way here to follow it. */
export type BuildState = 'building' | 'started' | 'waiting' | 'done' | 'failed';

/** How a build at work marks itself: the turn's own working orb, long work's live dot, or light passing across the
 *  word. The coordinator lab shows them side by side. */
export type BuildingLook = 'orb' | 'dot' | 'shine';
export const BUILDING_LOOK: BuildingLook = 'orb';

const BUILD_STATUS: Record<BuildState, { word: string; tone: 'done' | 'working' | 'failed' | 'idle' }> = {
    building: { word: 'Building', tone: 'working' },
    started: { word: 'Building', tone: 'idle' },
    waiting: { word: 'Needs you', tone: 'idle' },
    failed: { word: 'Stopped', tone: 'failed' },
    done: { word: 'Built', tone: 'done' },
};

function workingMark(look: BuildingLook): ReactNode {
    if (look === 'orb') return <ThinkingOrb state="shaping" size={20} style={{ width: 18, height: 18 }} aria-hidden />;
    if (look === 'dot') return <LiveDot />;
    return null;
}

/** Where a build stands, in a card's header: at work, its working mark beside "Building"; each change swaps in as the
 *  narrated line does, and a build seen finishing here draws its check in where the mark was. */
export function BuildStatus({ state, look = BUILDING_LOOK }: { state: BuildState; look?: BuildingLook }) {
    const sawWork = useRef(false);
    if (state === 'building') sawWork.current = true;
    const { word, tone } = BUILD_STATUS[state];
    const mark = state === 'building' ? workingMark(look) : state === 'done' && sawWork.current ? <FreshCheck check="draw" /> : undefined;
    return (
        <>
            <ProgressMotion />
            <Swap id={state} appear={false}>
                {/* Right-aligned, so a longer word on its way out overflows toward the title rather than off the card. */}
                <span className="flex justify-end whitespace-nowrap" data-testid="build-status" data-state={state}>
                    <Status state={tone} mark={mark}>
                        <span className={cn(state === 'building' && look === 'shine' && 'tl-shine')}>{word}</span>
                    </Status>
                </span>
            </Swap>
        </>
    );
}

const partKey = (part: BuildPart) => `${part.type}:${part.label}`;

/** The part that landed last: the newest one not seen before, held until another lands. A card that opens mid-build
 *  has watched nothing land, so it names the last part in the flow's order. */
function useLatestPart(parts: BuildPart[]): BuildPart | undefined {
    const seen = useRef<Set<string> | null>(null);
    const latest = useRef<BuildPart | undefined>(undefined);
    const landed = seen.current ? parts.filter((part) => !seen.current!.has(partKey(part))) : parts;
    if (landed.length) latest.current = landed[landed.length - 1];
    seen.current = new Set(parts.map(partKey));
    return latest.current && seen.current.has(partKey(latest.current)) ? latest.current : parts[parts.length - 1];
}

/** What NoClick is building, drawn as it goes on the canvas, the part that just landed named above it. What the
 *  builder asks you stands under the card as fields of its own, never inside it. */
export function AgentPreviewCard({
    blob,
    name,
    meta,
    state,
    parts,
    actions,
    onOpen,
    look,
}: {
    /** The graph so far; absent until the first part lands. */
    blob?: ScaffoldBlob;
    name: string;
    meta?: ReactNode;
    state: BuildState;
    parts: BuildPart[];
    actions?: ReactNode;
    /** Opens the automation, from the canvas's top-right corner. */
    onOpen?: () => void;
    look?: BuildingLook;
}) {
    const building = state === 'building';
    const latest = useLatestPart(parts);
    const line = building ? (latest ? `Adding ${latest.label}…` : 'Starting…') : `${parts.length} ${parts.length === 1 ? 'part' : 'parts'}`;
    return (
        <InlineCard
            title={name}
            meta={
                meta ?? (
                    <Swap id={line} appear={false}>
                        {line}
                    </Swap>
                )
            }
            aside={state === 'started' ? undefined : <BuildStatus state={state} look={look} />}
            actions={actions}
        >
            {blob && blob.nodes.length > 0 ? (
                <Canvas blob={blob} className={cn('transition-opacity duration-500', building && 'opacity-90')} onOpen={onOpen} />
            ) : (
                <div className="grid h-[120px] place-items-center rounded-xl bg-foreground/[0.03] text-[13px] text-muted-foreground">{building ? 'Drawing it…' : 'Nothing on the canvas yet'}</div>
            )}
        </InlineCard>
    );
}
