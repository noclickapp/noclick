/**
 * AgentRuntimePhase — the LIVE "Which agent should run it?" setup step. Same
 * composition as the design bench's RuntimePhase (/design/onboarding/guided)
 * but wired to real state: the selection derives from the agent node's
 * config.model, picking a card writes the model (plus wrapper sub-model seed)
 * through onConfigChange, card statuses come from the user's real saved
 * credentials, and the harness credential block mounts the real
 * NodeCredentials against the node itself.
 */

import { useEffect, useMemo, useState } from 'react';
import type { Node } from '@xyflow/react';
import { motion } from 'framer-motion';
import { ChevronDown } from 'lucide-react';
import { OpenAI } from '@lobehub/icons';
import { cn } from '~/lib/utils';
import { LogoMark } from '~/components/shared/LogoMark';
import { ModelPickerModal } from '~/components/workflow/ModelPickerModal';
import { NodeCredentials } from '~/components/workflow/NodeCredentials';
import { CredentialSurface } from '~/components/design/onboarding/CredentialSurface';
import { RUNTIME_CHOICES } from '~/components/design/onboarding/liveWorkflow';
import { HARNESSES, getHarnessModel } from '~/data/harness-content';
import { HARNESS_BRANDS, resolveAgentModelKind } from '~/lib/harnessBrand';
import {
    CLI_MODEL_PROVIDER,
    DEFAULT_AGENT_MODEL,
    LLM_HARNESS,
    harnessOf,
} from '~/lib/agentChat';
import {
    acceptedAgentCredentialTypes,
    getAgentEffectiveModel,
    getAgentSelectedModel,
    inferProviderFromPrefix,
    seedWrapperSubmodel,
} from '~/lib/agentCredentialModel';
import type { ModelProvider } from '~/types/provider';
import { useModels } from '~/hooks/useModels';
import { sendEventAsync } from '~/lib/socket-sender';
import { getAllCredentialsFromCache } from '~/utils/credentialAutoSelect';

interface CredentialRow {
    id: string;
    name: string;
    credential_type: string;
    created_at?: string;
}

/** Client-side brand lockup for a harness card — the bench used the
    server-serialized HarnessWordmark; this composes the same look from the
    client-safe HARNESS_BRANDS assets (wordmark img, or mark + brand-font name
    for the vendors without a public wordmark). */
function HarnessLockup({ slug, name }: { slug: string; name: string }) {
    if (slug === 'codex') {
        return (
            <span className="inline-flex items-center gap-1.5">
                <OpenAI
                    className="text-zinc-900 dark:text-white"
                    style={{ width: 24, height: 24 }}
                />
                <span className="font-brand text-[17px] font-semibold leading-none tracking-tight">
                    {name}
                </span>
            </span>
        );
    }
    const brand = HARNESS_BRANDS[slug as keyof typeof HARNESS_BRANDS];
    if (!brand) return <span className="text-[15px] font-medium">{name}</span>;
    if (brand.wordmarkSrc) {
        return (
            <span className="inline-flex items-center">
                <img src={brand.wordmarkSrc} alt={name} className="h-6 w-auto" />
            </span>
        );
    }
    // Claude Code: mark only — scale up past its internal whitespace, name in
    // the brand font (mirrors HarnessWordmark's card size).
    return (
        <span className="inline-flex items-center gap-1.5">
            <img src={brand.markSrc} alt="" className="h-6 w-6 scale-[1.4]" />
            <span className="font-brand text-[17px] font-semibold leading-none tracking-tight">
                {name}
            </span>
        </span>
    );
}

/** The config patch selecting a model — model id, display label, and wrapper
    submodel seeding — shared by the phase's own picker and the setup footer's
    "continue with platform models" switch. */
export function buildModelPatch(
    modelId: string,
    config: Record<string, unknown>,
    getModelById: (id: string) => { name?: string } | undefined
): Record<string, unknown> {
    const label =
        getModelById(modelId)?.name ?? HARNESSES[modelId]?.displayName ?? modelId;
    return {
        model: modelId,
        model__label: label,
        ...seedWrapperSubmodel(modelId, config),
    };
}

export function AgentRuntimePhase({
    node,
    onConfigChange,
    onCredentialIdsChange,
}: {
    node: Node;
    onConfigChange: (nodeId: string, config: Record<string, any>) => void;
    onCredentialIdsChange: (nodeId: string, credentialIds: Record<string, string>) => void;
}) {
    const config = (node.data?.config as Record<string, unknown>) ?? {};
    const credentialIds = (node.data?.credentialIds as Record<string, string>) ?? {};
    const { models, getModelById } = useModels();

    const selectedModel = getAgentSelectedModel(undefined, config);
    const currentHarness = harnessOf(selectedModel);
    const selectedSlug = currentHarness === LLM_HARNESS ? 'sdk' : currentHarness;

    // The user's saved credentials — cache for instant paint, one live fetch
    // for truth, re-fetched after a connect lands on the node so the card
    // pills flip without a remount.
    const [saved, setSaved] = useState<CredentialRow[]>(
        () => getAllCredentialsFromCache() as CredentialRow[]
    );
    const attachedKey = JSON.stringify(credentialIds);
    useEffect(() => {
        let cancelled = false;
        (async () => {
            try {
                const res: any = await sendEventAsync({
                    event_name: 'credential:list',
                    request_id: crypto.randomUUID(),
                } as any);
                if (!cancelled && Array.isArray(res?.credentials)) {
                    setSaved(res.credentials);
                }
            } catch {
                // Cache seed stands; statuses degrade to the requirement copy.
            }
        })();
        return () => {
            cancelled = true;
        };
    }, [attachedKey]);

    // Newest saved credential that would satisfy each harness. Wrappers
    // (openclaw/hermes/opencode) are resolved through their default sub-model,
    // so e.g. OpenClaw matches an agent_openrouter credential.
    const savedFor = useMemo(() => {
        const out: Record<string, CredentialRow | undefined> = {};
        for (const choice of RUNTIME_CHOICES) {
            if (!choice.requiresOwnAccount) continue;
            const model = getHarnessModel(choice.slug) ?? choice.slug;
            const effective = getAgentEffectiveModel(model, {});
            const provider = (getModelById(effective)?.provider ??
                inferProviderFromPrefix(effective) ??
                CLI_MODEL_PROVIDER[choice.slug] ??
                null) as ModelProvider | null;
            const accepted = new Set(acceptedAgentCredentialTypes(provider));
            out[choice.slug] = saved
                .filter((c) => accepted.has(c.credential_type))
                .sort((a, b) => (b.created_at ?? '').localeCompare(a.created_at ?? ''))[0];
        }
        return out;
    }, [saved, getModelById]);

    const writeModel = (modelId: string) => {
        onConfigChange(node.id, {
            ...config,
            ...buildModelPatch(modelId, config, getModelById),
        });
    };

    const pick = (slug: string) => {
        if (slug === selectedSlug) return;
        if (slug === 'sdk') {
            // Only leave the CLI model behind — a platform model already
            // chosen is the user's pick, not ours to reset.
            if (currentHarness !== LLM_HARNESS) writeModel(DEFAULT_AGENT_MODEL);
            return;
        }
        const model = getHarnessModel(slug);
        if (model) writeModel(model);
    };

    const [picking, setPicking] = useState(false);
    const chosen = RUNTIME_CHOICES.find((c) => c.slug === selectedSlug);
    const chosenName =
        selectedSlug === 'sdk'
            ? 'Platform managed'
            : (HARNESSES[selectedSlug]?.displayName ?? selectedSlug);
    const modelName = getModelById(selectedModel)?.name ?? selectedModel;

    return (
        <div>
            <h2 className="mb-0 font-sans text-[22px] font-semibold tracking-[-0.02em]">
                Which agent should run it?
            </h2>
            <p className="mb-0 mt-2 text-[14px] leading-relaxed text-foreground/45">
                The last choice, and the only one that can ask for another
                account.
            </p>

            <div className="mt-6 grid gap-2 sm:grid-cols-2">
                {RUNTIME_CHOICES.map((h) => {
                    const active = h.slug === selectedSlug;
                    const managed = !h.requiresOwnAccount;
                    const cred = savedFor[h.slug];
                    const name = managed
                        ? 'Platform managed'
                        : (HARNESSES[h.slug]?.displayName ?? h.slug);
                    return (
                        <button
                            key={h.slug}
                            onClick={() => pick(h.slug)}
                            aria-pressed={active}
                            className={cn(
                                'flex flex-col items-start gap-2 rounded-xl border px-4 py-3.5 text-left transition-colors',
                                active
                                    ? 'border-foreground/40 bg-foreground/[0.05]'
                                    : 'border-foreground/10 hover:border-foreground/25'
                            )}
                        >
                            <div className="flex min-h-[26px] w-full items-center gap-2">
                                {managed ? (
                                    <span className="inline-flex items-center gap-2">
                                        <LogoMark className="h-5 w-5" />
                                        <span className="font-brand text-[17px] font-semibold leading-none tracking-tight">
                                            {name}
                                        </span>
                                    </span>
                                ) : (
                                    <HarnessLockup slug={h.slug} name={name} />
                                )}
                                {(managed || cred) && (
                                    <span className="ml-auto shrink-0 rounded-full bg-emerald-400/10 px-2 py-0.5 text-[10.5px] font-medium text-emerald-400">
                                        {managed ? 'Ready' : 'Connected'}
                                    </span>
                                )}
                            </div>
                            <span className="w-full truncate text-[12.5px] leading-snug text-foreground/40">
                                {managed
                                    ? 'Runs on our key'
                                    : (cred?.name ??
                                      (h as { requirement?: string }).requirement ??
                                      'Your own account')}
                            </span>
                        </button>
                    );
                })}
            </div>

            {/* Managed: the model choice lives below the grid — a nested
                control inside a button is cramped and an accessibility smell. */}
            {selectedSlug === 'sdk' && (
                <motion.button
                    initial={{ opacity: 0, y: 6 }}
                    animate={{ opacity: 1, y: 0 }}
                    onClick={() => setPicking((v) => !v)}
                    aria-expanded={picking}
                    className="mt-3 flex w-full items-center gap-3 rounded-lg border border-foreground/12 px-3.5 py-2.5 text-left transition-colors hover:border-foreground/25"
                >
                    <span className="shrink-0 text-[12.5px] text-foreground/35">
                        Model
                    </span>
                    <span className="min-w-0 flex-1 truncate text-[13.5px] text-foreground/85">
                        {modelName}
                    </span>
                    <ChevronDown
                        className={cn(
                            'h-3.5 w-3.5 shrink-0 text-foreground/35 transition-transform',
                            picking && 'rotate-180'
                        )}
                    />
                </motion.button>
            )}
            <ModelPickerModal
                open={picking}
                onClose={() => setPicking(false)}
                selectedModelId={selectedModel}
                models={models}
                onModelSelect={(id) => {
                    writeModel(id);
                    setPicking(false);
                }}
            />

            {/* Harness: the real agent credential UI against the real node —
                pick a saved credential, connect a new one, or disconnect. */}
            {chosen?.requiresOwnAccount && (
                <motion.div
                    key={selectedSlug}
                    initial={{ opacity: 0, y: 6 }}
                    animate={{ opacity: 1, y: 0 }}
                    className="mt-4 rounded-xl border border-foreground/12 p-4"
                >
                    <p className="m-0 text-[13px] font-medium">{chosenName} account</p>
                    <CredentialSurface className="mt-3">
                        <NodeCredentials
                            nodeType="agent"
                            nodeData={{ config }}
                            credentialIds={credentialIds}
                            onChange={(ids) => onCredentialIdsChange(node.id, ids)}
                            compact
                        />
                    </CredentialSurface>
                    {!savedFor[selectedSlug] && (
                        <button
                            onClick={() => pick('sdk')}
                            className="mt-3 rounded-lg border border-foreground/15 px-3.5 py-1.5 text-[12.5px] text-foreground/70 transition-colors hover:bg-foreground/5 hover:text-foreground"
                        >
                            Use ours instead
                        </button>
                    )}
                </motion.div>
            )}
        </div>
    );
}
