// Setting an agent up without leaving the thread: the apps it needs, each with the one thing that connects it, the
// accounts a turn asks for on one card (a row each, connected from its row), and the agent itself drawn on a canvas
// while it's built.
import { useRef, type ReactNode } from 'react';
import { useSlot } from '@/slots';
import type { SavedGraph } from '@/lib/graphPreview';
import { cn } from '@/ui/utils';
import { Canvas } from '@/ui/chat/canvas';
import { FreshCheck, ProgressMotion, Swap } from '@/ui/chat/motion';
import { AskCard, InlineCard, listOf, LiveDot, PILL_QUIET, Receipt, Row, Rows, Status } from '@/ui/chat/primitives';
import { WORKING_MARK } from '../../slots';

/** What a connect-time check said of an account, as the app's connections report it (the fields read here). */
export interface ConnectionCheck {
    reachable?: boolean | null;
    samples?: { label: string }[] | null;
    total?: number | null;
    noun?: string | null;
    account_label?: string | null;
    proves?: string | null;
}

/** Why a link's request can't be provided: it was, it ended, it's gone, or it couldn't be read. */
export type ProvideRequestProblem = 'fulfilled' | 'cancelled' | 'expired' | 'not_found' | 'too_many' | 'failed' | 'unreachable';

/** A check that ran and could neither prove nor refuse the account: saved, never shown as working. */
const unverified = (verification: ConnectionCheck) => verification.reachable !== true && verification.reachable !== false;

/** What a working check proved, in one line: what it listed ("channels: #general, #sales +3 more"), else whom it
 *  reached. */
function verdictSummary(verification: ConnectionCheck | null | undefined): string | null {
    if (!verification || verification.reachable !== true) return null;
    const samples = (verification.samples ?? []).map((s) => s.label);
    if (samples.length) {
        const more = verification.total && verification.total > samples.length ? ` +${verification.total - samples.length} more` : '';
        return `${verification.noun ?? 'items'}: ${samples.join(', ')}${more}`;
    }
    if (verification.account_label) return verification.account_label;
    return verification.proves === 'reachability' ? 'key accepted' : 'connected';
}

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

/** An account that's in: who it is, what the connect-time check said when it just ran here, and who connected it
 *  where others may have (a channel: "Priya", "You"). */
export interface ConnectedAccount {
    name: string;
    account?: string;
    verification?: ConnectionCheck | null;
    by?: string;
}

/** A key nothing could check is saved, never shown as working. */
const savedOnly = (verification?: ConnectionCheck | null) => !!verification && unverified(verification);

/** What the check proved (their customers, their channels), else the account itself. */
const accountLine = ({ account, verification }: ConnectedAccount) => verdictSummary(verification) ?? account;

/** The accounts a turn asks to connect, as one card of asks: a row each (its mark, its name, what it's for and the one
 *  button that connects it). Once every one is in, the card folds to `ConnectedSummary`. */
export function ConnectAccountsCard({ children }: { children: ReactNode }) {
    return <AskCard testId="coordinator-connect">{children}</AskCard>;
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

/** Every account in, in one line, saying who connected them where they all had one person. */
export function ConnectedSummary({ accounts }: { accounts: ConnectedAccount[] }) {
    if (accounts.length === 1) return <ConnectedReceipt {...accounts[0]} />;
    const saved = accounts.filter((a) => savedOnly(a.verification)).map((a) => a.name);
    const connected = accounts.filter((a) => !savedOnly(a.verification)).map((a) => a.name);
    if (!connected.length) return <Receipt tone="info">{listOf(saved)} saved, not verified yet · the first run will tell</Receipt>;
    const by = accounts.every((a) => a.by && a.by === accounts[0].by) ? accounts[0].by : undefined;
    return (
        <Receipt>
            {by ? `${by} connected ${listOf(connected)}` : `${listOf(connected)} ${connected.length === 1 ? 'is' : 'are'} connected`}
            {saved.length ? ` · ${listOf(saved)} saved, not verified yet` : ''}
        </Receipt>
    );
}

/** A connected account in one line: who connected it where that's said, then what the connect-time check proved when
 *  it just ran here, else the account itself. */
export function ConnectedReceipt({ name, account, verification, by }: ConnectedAccount) {
    if (savedOnly(verification)) return <Receipt tone="info">{name} saved, not verified yet · the first run will tell</Receipt>;
    const line = accountLine({ name, account, verification });
    return (
        <Receipt>
            {by ? `${by} connected ${name}` : `${name} connected`}
            {line ? ` · ${line}` : ''}
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

function workingMark(look: BuildingLook, Orb: () => ReactNode): ReactNode {
    if (look === 'orb') return <Orb />;
    if (look === 'dot') return <LiveDot />;
    return null;
}

/** Where a build stands, in a card's header: at work, its working mark beside "Building"; each change swaps in as the
 *  narrated line does, and a build seen finishing here draws its check in where the mark was. */
export function BuildStatus({ state, look = BUILDING_LOOK }: { state: BuildState; look?: BuildingLook }) {
    const sawWork = useRef(false);
    const Orb = useSlot(WORKING_MARK);
    if (state === 'building') sawWork.current = true;
    const { word, tone } = BUILD_STATUS[state];
    const mark = state === 'building' ? workingMark(look, Orb) : state === 'done' && sawWork.current ? <FreshCheck check="draw" /> : undefined;
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
    blob?: SavedGraph;
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
