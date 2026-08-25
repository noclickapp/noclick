/* The setup phases' shared building blocks: the Mark family and
   CredentialPhase, consumed by the production WorkflowSetupView. The design
   bench variants that iterated on the full phase set were removed once the
   composition shipped.

   The test button is capability-scoped, not auth-only: a valid token missing one
   scope authenticates fine and fails mid-run, which is the failure an "is it
   connected" check cannot see. */

import { useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { AnimatePresence, motion } from 'framer-motion';
import { AlertTriangle, Check, Loader2, RotateCw, Sparkles } from 'lucide-react';
import { NodeCredentials } from '~/components/workflow/NodeCredentials';
import { sendEventAsync, CredentialTestConnectionRequest } from '~/lib/socket-sender';
import type { CredentialTestConnectionResponse } from '~/types/socket-events.generated';
import { CredentialSurface } from './CredentialSurface';
import { Mark } from './primitives';

// Mark moved to primitives (registry-free) so the marketing wizard can share
// it; re-exported here for existing importers.
export { Mark } from './primitives';
import { SerializedIcon } from '~/components/shared/SerializedIcon';
import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from '~/components/ui/select';
import { cn } from '~/lib/utils';
import type { CredentialStep, TestOutcome } from './types';

/* ------------------------------------------------------- 1. credentials */

function TestResult({
    step,
    outcome,
    evidence: accountLine,
    onReconnect,
    evidenceLive: evidence,
    onPick,
    picked,
}: {
    step: CredentialStep;
    outcome: TestOutcome;
    /** Tied to the account actually selected, not the one captured. */
    evidence?: string;
    onReconnect: () => void;
    /** Live probe result; null until the test has run. */
    evidenceLive: CredentialTestConnectionResponse | null;
    /** Set the field the evidence can answer. */
    onPick: (value: string) => void;
    picked: string;
}) {
    if (outcome === 'working') {
        // The samples ARE the proof, so they lead — at full contrast, in the
        // user's own words. Naming the account is the supporting line, not the
        // headline: "Read 14 mailbox labels" is a receipt, "#sales, #gtm" is
        // something only their workspace could have produced.
        //
        // And when the probe went through the field's own options loader, those
        // same samples are legal values for it — so proving the connection and
        // choosing the resource become one interaction instead of two. Picking
        // here is the difference between a question asked and a question
        // already answered.
        const live = evidence?.samples ?? [];
        const samples = live.length
            ? live.map((s) => s.label)
            : step.evidenceSamples ?? [];
        const canPick =
            Boolean(evidence?.answers_field) && evidence?.answers_field === step.rebind?.name;
        const more = evidence?.total && evidence.total > samples.length
            ? evidence.total - samples.length
            : step.evidenceMore;
        return (
            <div className="mt-3 rounded-lg border border-emerald-400/25 bg-emerald-400/[0.06] px-3.5 py-3">
                <div className="flex gap-2.5">
                    <Check className="mt-0.5 h-4 w-4 shrink-0 text-emerald-400" />
                    <div className="min-w-0">
                        {samples.length > 0 ? (
                            <>
                                <p className="m-0 text-[13.5px] leading-relaxed">
                                    <span className="text-foreground/55">
                                        Your {evidence?.noun ?? step.evidenceNoun ?? 'items'}
                                        {canPick ? ' — pick one' : ''}:{' '}
                                    </span>
                                    {canPick ? (
                                        <span className="inline-flex flex-wrap gap-1.5 align-middle">
                                            {(evidence?.samples ?? []).map((s) => (
                                                <button
                                                    key={s.value ?? s.label}
                                                    onClick={() => onPick(s.value ?? s.label)}
                                                    className={cn(
                                                        'rounded-md border px-2 py-0.5 text-[12.5px] transition-colors',
                                                        picked === (s.value ?? s.label)
                                                            ? 'border-emerald-400/50 bg-emerald-400/15 font-medium text-foreground'
                                                            : 'border-foreground/15 text-foreground/80 hover:border-foreground/35 hover:bg-foreground/5'
                                                    )}
                                                >
                                                    {s.label}
                                                </button>
                                            ))}
                                        </span>
                                    ) : (
                                        <span className="font-medium text-foreground/95">
                                            {samples.join(', ')}
                                        </span>
                                    )}
                                    {more ? (
                                        <span className="text-foreground/40"> +{more} more</span>
                                    ) : null}
                                </p>
                                {(evidence?.account_label || accountLine) && (
                                    <p className="mb-0 mt-1 text-[12px] text-foreground/40">
                                        {evidence?.account_label ?? accountLine}
                                    </p>
                                )}
                            </>
                        ) : (
                            <>
                                <p className="m-0 text-[13.5px] font-medium">Working</p>
                                <p className="mb-0 mt-0.5 text-[12.5px] leading-relaxed text-foreground/55">
                                    {evidence?.account_label ?? accountLine}
                                </p>
                            </>
                        )}
                    </div>
                </div>
            </div>
        );
    }
    if (outcome === 'partial') {
        const names = step.tools
            .filter((t) => step.unverifiedOps?.includes(t.value))
            .map((t) => t.name);
        return (
            <div className="mt-3 rounded-lg border border-amber-400/30 bg-amber-400/[0.06] px-3.5 py-3">
                <div className="flex gap-2.5">
                    <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-400" />
                    <div className="min-w-0">
                        <p className="m-0 text-[13.5px] font-medium">Missing permission</p>
                        <p className="mb-0 mt-0.5 text-[12.5px] leading-relaxed text-foreground/55">
                            Signed in, but{' '}
                            {names.length ? (
                                <b className="font-medium text-foreground/80">{names.join(' and ')}</b>
                            ) : (
                                'some actions'
                            )}{' '}
                            couldn&rsquo;t be confirmed. It will fail partway through a run.
                        </p>
                        <button
                            onClick={onReconnect}
                            className="mt-2.5 inline-flex items-center gap-2 rounded-lg border border-foreground/15 px-3 py-1.5 text-[12.5px] transition-colors hover:bg-foreground/5"
                        >
                            <RotateCw className="h-3 w-3" /> Reconnect
                        </button>
                    </div>
                </div>
            </div>
        );
    }
    return (
        <div className="mt-3 rounded-lg border border-red-400/25 bg-red-400/[0.06] px-3.5 py-3">
            <div className="flex gap-2.5">
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-red-400" />
                <div className="min-w-0">
                    <p className="m-0 text-[13.5px] font-medium">{step.label} rejected this account</p>
                    {(evidence?.error || step.testError) && (
                        <p className="mb-0 mt-2 font-mono text-[11.5px] text-red-400/80">
                            {evidence?.error ?? step.testError}
                        </p>
                    )}
                    <button
                        onClick={onReconnect}
                        className="mt-2.5 inline-flex items-center gap-2 rounded-lg bg-primary px-3.5 py-1.5 text-[12.5px] font-medium text-primary-foreground transition-opacity hover:opacity-90"
                    >
                        <RotateCw className="h-3 w-3" /> Reconnect {step.label}
                    </button>
                </div>
            </div>
        </div>
    );
}

export function CredentialPhase({
    step,
    bound,
    onBind,
    credentialIds,
    onCredentialsChange,
    onVerdict,
    testSlot,
}: {
    step: CredentialStep;
    bound: string;
    onBind: (v: string) => void;
    /** The node's real credentialIds map, owned by the flow so the skip warning
        and the gate can read it from any step. */
    credentialIds: Record<string, string>;
    onCredentialsChange: (ids: Record<string, string>) => void;
    /** Report the probe's verdict up so the persistent rail can warn about a
        credential that is attached but dead — invisible otherwise. */
    onVerdict?: (failed: boolean, error?: string) => void;
    /** Portal target for the Test Connection button (the host's footer) —
        results still render in the step body. */
    testSlot?: HTMLElement | null;
}) {
    const [outcome, setOutcome] = useState<TestOutcome>('untested');
    const [testing, setTesting] = useState(false);
    const [toolsOpen, setToolsOpen] = useState(false);

    // Detaching returns the real NodeCredentials to its connect state, so the
    // provider's actual OAuth flow runs — rather than a second, divergent
    // reconnect path that would drift from the product's.
    const credentialRef = useRef<HTMLDivElement>(null);
    // A preset is the effective value until the importer chooses otherwise, so
    // the step arrives already correct rather than pending.
    const value = bound || step.rebind?.preset || '';
    const [repointing, setRepointing] = useState(false);
    const reconnect = () => {
        onCredentialsChange({});
        setOutcome('untested');
        credentialRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    };

    // The real probe, not a simulation: asks the provider to prove the attached
    // credential works and comes back with the user's own channels or repos.
    const [evidence, setEvidence] = useState<CredentialTestConnectionResponse | null>(null);
    const runTest = async () => {
        if (!attachedId) return;
        setTesting(true);
        setEvidence(null);
        try {
            const res = await sendEventAsync(
                CredentialTestConnectionRequest.create({
                    node_type: step.id,
                    credential_id: attachedId,
                })
            );
            setEvidence(res);
            onVerdict?.(res.reachable === false, res.error ?? undefined);
            // Tri-state: `null` means the probe could not judge, which is not
            // grounds for telling someone their credential is dead. It reads as
            // connected-but-unproven, the same as an untested one.
            setOutcome(res.reachable === false ? 'failed' : 'working');
        } catch {
            setOutcome('working');
        } finally {
            setTesting(false);
        }
    };

    // Writes first: the three operations we name should be the notable ones,
    // not whatever the schema happened to list first.
    const WRITES = /^(send|post|update|delete|create|remove|archive|invite|set|rename|schedule|add|edit)/i;
    const ordered = [
        ...step.tools.filter((t) => WRITES.test(t.name)),
        ...step.tools.filter((t) => !WRITES.test(t.name)),
    ];
    const shownTools = ordered.slice(0, 3);
    const restTools = ordered.slice(3);
    const restByCategory = restTools.reduce<Record<string, typeof restTools>>((acc, t) => {
        (acc[t.category] ??= []).push(t);
        return acc;
    }, {});
    const restCategories = Object.keys(restByCategory).slice(0, 3);

    const attachedId = Object.values(credentialIds).find(Boolean) ?? null;
    const attached = step.options.find((o) => o.id === attachedId) ?? null;
    const hasCredential = Boolean(attachedId);

    return (
        <div>
            <Mark iconHtml={step.iconHtml} iconColor={step.iconColor} iconNode={step.iconNode} size="lg" />

            <h2 className="mb-0 mt-5 font-sans text-[22px] font-semibold tracking-[-0.02em]">
                {step.label}
            </h2>
            <p className="mb-0 mt-3 text-[15px] leading-relaxed text-foreground/55">{step.why}</p>

            {/* The real product credential UI: lists the account's credentials for
                this node type, runs the actual OAuth flow, creates/deletes over
                the socket. Same component the config panel renders. */}
            <CredentialSurface className="mt-5" ref={credentialRef}>
                <NodeCredentials
                    nodeType={step.id}
                    credentialIds={credentialIds}
                    onChange={(ids) => {
                        onCredentialsChange(ids);
                        setOutcome('untested');
                        setEvidence(null);
                        onVerdict?.(false);
                    }}
                    compact
                />
            </CredentialSurface>

            {/* What this credential buys the agent, as a sentence. The overflow
                link names the areas it covers, so it informs before it is
                clicked, and opens a grouped breakdown when it is. Height is
                constant whether the allowlist holds 2 operations or 200 —
                Slack alone exposes 207, so that is the case that matters. */}
            {step.tools.length > 0 && (
                <div className="mt-5">
                    <p className="mb-0 text-[13.5px] leading-relaxed text-foreground/55">
                        It can{' '}
                        <span className="text-foreground/90">
                            {shownTools.map((t) => t.name.toLowerCase()).join(', ')}
                        </span>
                        {restTools.length > 0 && (
                            <>
                                , and{' '}
                                <button
                                    onClick={() => setToolsOpen((v) => !v)}
                                    aria-expanded={toolsOpen}
                                    className="text-foreground/90 underline decoration-foreground/25 underline-offset-2 transition-colors hover:decoration-foreground/70"
                                >
                                    {restTools.length} more across {restCategories.join(', ')}
                                </button>
                            </>
                        )}
                        . Nothing else.
                    </p>

                    <AnimatePresence initial={false}>
                        {toolsOpen && restTools.length > 0 && (
                            <motion.div
                                initial={{ opacity: 0, height: 0 }}
                                animate={{ opacity: 1, height: 'auto' }}
                                exit={{ opacity: 0, height: 0 }}
                                transition={{ duration: 0.2 }}
                                className="overflow-hidden"
                            >
                                <div className="mt-3 max-h-[200px] space-y-2.5 overflow-y-auto rounded-lg border border-foreground/10 p-3">
                                    {Object.entries(restByCategory).map(([cat, list]) => (
                                        <div key={cat}>
                                            <p className="m-0 text-[11px] font-semibold uppercase tracking-[0.1em] text-foreground/30">
                                                {cat}
                                            </p>
                                            <p className="mb-0 mt-1 text-[12px] leading-relaxed text-foreground/55">
                                                {list.map((t) => t.name).join(' · ')}
                                            </p>
                                        </div>
                                    ))}
                                </div>
                            </motion.div>
                        )}
                    </AnimatePresence>
                </div>
            )}

            {/* Prove it works before moving on. The button itself lives in
                the host's FOOTER when a slot is provided (beside Continue —
                part of the step, not the credential form); results always
                render here in the step body. */}
            {(() => {
                const testButton = (
                    <button
                        onClick={runTest}
                        disabled={testing || !hasCredential}
                        className="inline-flex items-center gap-2 rounded-lg border border-foreground/15 px-3.5 py-2.5 text-[13.5px] font-medium transition-colors hover:bg-foreground/5 disabled:opacity-40"
                    >
                        {testing ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />}
                        {testing ? 'Checking…' : outcome === 'untested' ? 'Test Connection' : 'Test again'}
                    </button>
                );
                return testSlot ? createPortal(testButton, testSlot) : <div className="mt-5">{testButton}</div>;
            })()}
            <div className="mt-5">
                {!testing && outcome !== 'untested' && (
                    <TestResult
                        step={step}
                        outcome={outcome}
                        evidence={attached ? step.testEvidence : 'Authenticated.'}
                        onReconnect={reconnect}
                        evidenceLive={evidence}
                        onPick={onBind}
                        picked={value}
                    />
                )}
            </div>

            {/* A saved value is only worth asking about when it points at
                something only the AUTHOR has — their #sales does not exist in
                your workspace. INBOX is INBOX everywhere, so a preset is
                confirmed in one line instead of presented as an empty
                "Choose one…", which reads as an unfinished task. */}
            {step.rebind && outcome === 'working' && (
                <div className="mt-7 border-t border-foreground/[0.07] pt-5">
                    {step.rebind.preset && !repointing ? (
                        <p className="m-0 text-[13px] text-foreground/45">
                            {step.rebind.presetLabel ?? step.rebind.label}{' '}
                            <span className="font-medium text-foreground/85">
                                {step.rebind.options.find((o) => o.value === value)?.label ??
                                    value}
                            </span>
                            <button
                                onClick={() => setRepointing(true)}
                                className="ml-2 underline decoration-foreground/25 underline-offset-2 transition-colors hover:decoration-foreground/70"
                            >
                                change
                            </button>
                        </p>
                    ) : (
                        <>
                            <p className="mb-2 text-[12.5px] text-foreground/40">
                                {step.rebind.label}
                            </p>
                            <Select value={value} onValueChange={onBind}>
                                <SelectTrigger className="w-full">
                                    <SelectValue placeholder="Choose one…" />
                                </SelectTrigger>
                                <SelectContent>
                                    {step.rebind.options.map((o) => (
                                        <SelectItem key={o.value} value={o.value}>
                                            {o.label}
                                        </SelectItem>
                                    ))}
                                </SelectContent>
                            </Select>
                        </>
                    )}
                </div>
            )}
        </div>
    );
}
