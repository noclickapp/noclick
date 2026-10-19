// Setting an agent up without leaving the thread: the apps it needs, each with the one thing that connects it, one
// account connected right on its card, and the agent itself drawn on a canvas while it's built.
import { Fragment, useRef, useState, type ReactNode } from 'react';
import { verdictState, verdictSummary } from '~/components/credential/ConnectionVerdict';
import type { ProvideCredentialMethod } from '~/components/credential/CredentialMethodConnect';
import type { ProvideRequestProblem } from '~/components/credential/CredentialProvideFlow';
import type { ScaffoldBlob } from '~/lib/agentScaffold';
import { kindFromBackendMethod } from '~/lib/credentialMethodKind';
import { cn } from '~/lib/utils';
import type { CredentialTestConnectionResponse } from '~/types/socket-events.generated';
import { ThinkingOrb } from '~/components/shared/ThinkingOrb';
import { Canvas } from './canvas';
import { FreshCheck, ProgressMotion, Swap } from './motion';
import { InlineCard, LiveDot, PILL_PRIMARY, PILL_QUIET, PILL_SECONDARY, Receipt, Row, Rows, Status } from './primitives';

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

/** How a way in reads as the switch to it, beside the one the card leads with. */
function otherWay(method: ProvideCredentialMethod, name: string): string {
    switch (kindFromBackendMethod(method)) {
        case 'oauth':
            return `Sign in with ${name} instead`;
        case 'qr_scan':
            return 'Scan a QR code instead';
        case 'agent_oauth':
            return 'Sign in with your plan instead';
        default:
            return `Use ${/^[aeiou]/i.test(method.label) ? 'an' : 'a'} ${method.label} instead`;
    }
}

/** One account to connect, connected on the card itself: its mark and what it's for, then the way in (a key's
 *  fields, a sign-in that opens in a small window over the chat, or a QR code once asked for, since showing one
 *  holds a WhatsApp connection open), with a quiet switch to the request's other ways in. `renderMethod` draws a
 *  way in: the product's own connect form, run on the request. */
export function ConnectAccountCard({
    mark,
    name,
    meta,
    methods,
    requested,
    renderMethod,
    showQr = false,
}: {
    mark: ReactNode;
    name: string;
    meta?: ReactNode;
    /** The request's ways in; absent while it loads. */
    methods?: ProvideCredentialMethod[];
    /** The credential type asked for: its way in leads. */
    requested: string;
    renderMethod: (method: ProvideCredentialMethod) => ReactNode;
    /** Start with the QR code showing. */
    showQr?: boolean;
}) {
    const [chosen, setChosen] = useState(requested);
    const [qrShown, setQrShown] = useState(showQr);
    const method = methods?.find((m) => m.credential_type === chosen) ?? methods?.[0];
    const kind = method && kindFromBackendMethod(method);
    const holding = kind === 'qr_scan' && !qrShown;
    const others = methods?.filter((m) => m !== method) ?? [];
    return (
        <InlineCard
            lead={mark}
            title={`Connect ${name}`}
            meta={meta}
            actions={
                (holding || others.length > 0) && (
                    <>
                        {holding && (
                            <button type="button" className={PILL_PRIMARY} onClick={() => setQrShown(true)} data-testid="coordinator-connect-qr">
                                Show QR code
                            </button>
                        )}
                        {others.map((other) => (
                            <button key={other.credential_type} type="button" className={PILL_QUIET} onClick={() => setChosen(other.credential_type)}>
                                {otherWay(other, name)}
                            </button>
                        ))}
                    </>
                )
            }
        >
            {!method ? (
                <Status state="working">Getting it ready</Status>
            ) : holding ? null : (
                <div className="space-y-2" data-testid="coordinator-connect-form">
                    <Fragment key={method.credential_type}>{renderMethod(method)}</Fragment>
                </div>
            )}
        </InlineCard>
    );
}

/** A sign-in the card can't finish (it asks which account or project to use once you're in, which only the app's
 *  own connect form can do): where to connect it instead. Connecting there doesn't answer the request, so NoClick
 *  is told by hand. */
export function ConnectElsewhere({ name, place, onOpen }: { name: string; place: string; onOpen: () => void }) {
    return (
        <div className="space-y-3">
            <p className="text-[13.5px] leading-relaxed text-muted-foreground">
                Signing in to {name} needs a step that only runs in {place}. Connect it there, then tell NoClick it’s done.
            </p>
            <button type="button" className={PILL_SECONDARY} onClick={onOpen}>
                Open {place}
            </button>
        </div>
    );
}

/** A connected account in one line: what the connect-time check proved when it just ran here (their customers,
 *  their channels), else the account itself. A key nothing could check is saved, never shown as working. */
export function ConnectedReceipt({ name, account, verification }: { name: string; account?: string; verification?: CredentialTestConnectionResponse | null }) {
    if (verification && verdictState(verification) === 'unverified') {
        return <Receipt tone="info">{name} saved, not verified yet · the first run will tell</Receipt>;
    }
    const line = verdictSummary(verification) ?? account;
    return (
        <Receipt>
            {name} connected{line ? ` · ${line}` : ''}
        </Receipt>
    );
}

/** A request that can no longer be connected here, and the way on: a new request from NoClick, or another try when
 *  it just couldn't be read. */
export function ConnectUnavailable({ name, problem, onRetry }: { name: string; problem: ProvideRequestProblem; onRetry: () => void }) {
    if (problem === 'failed' || problem === 'unreachable') {
        return (
            <Receipt
                tone="info"
                action={
                    <button type="button" className={cn(PILL_QUIET, 'h-7')} onClick={onRetry}>
                        Try again
                    </button>
                }
            >
                Couldn’t load the way to connect {name}
            </Receipt>
        );
    }
    const why =
        problem === 'too_many'
            ? `Too many tries to connect ${name}`
            : problem === 'cancelled'
              ? `The request to connect ${name} was cancelled`
              : problem === 'not_found'
                ? `A newer request to connect ${name} replaced this one`
                : `${name} wasn’t connected in time`;
    return <Receipt tone="info">{why} · ask NoClick again</Receipt>;
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
