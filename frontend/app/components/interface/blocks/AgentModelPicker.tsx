// Header model trigger for the AgentChatBlock. Renders the selected model as a
// heading (replacing the agent label) and, on click, opens the shared
// ModelPickerModal — the same rich picker the canvas agent node uses (search +
// provider rail + capability filters + favorites) — instead of a bespoke
// dropdown. The trigger's icon/name are resolved from the agent's
// load_field_options list (via the socket `workflow:node:load_options` path
// against agent.load_field_options), which guarantees the CLI-harness
// pseudo-models (claude-code, codex, opencode, openclaw, hermes) and their
// compact provider markers resolve correctly. Module-level cache so reopening /
// remounting the block keeps the trigger instant.

import { useState, useEffect, useMemo, useCallback } from 'react';
import { ChevronDown } from 'lucide-react';
import { sendEventAsync, WorkflowNodeLoadOptionsRequest } from '~/lib/socket-sender';
import type { WorkflowNodeLoadOptionsResponse, FieldOption } from '~/types/socket-events.generated';
import { getProviderMetadata, ModelProvider } from '~/types/provider';
import { useModels } from '~/hooks/useModels';
import { ModelPickerModal } from '~/components/workflow/ModelPickerModal';

// CLI harnesses pinned to the top of the picker — same set the canvas agent
// node uses (AGENT_NODE_PRIORITY_MODELS in AIAgentNode).
const PRIORITY_MODELS = ['codex', 'claude-code', 'opencode', 'openclaw', 'hermes'] as const;

interface AgentModelPickerProps {
  selectedModelId: string;
  onSelect: (modelId: string) => void;
  // Incrementing counter that imperatively opens the picker — lets the
  // credential-error banner's "Change model" button pop the modal open.
  openSignal?: number;
}

// Module-level cache so reopening the chat doesn't trigger a fresh load.
let cachedOptions: FieldOption[] | null = null;
let inflight: Promise<FieldOption[]> | null = null;

function loadAgentModelOptions(): Promise<FieldOption[]> {
  if (cachedOptions) return Promise.resolve(cachedOptions);
  if (inflight) return inflight;
  inflight = (async () => {
    try {
      const resp = (await sendEventAsync(
        WorkflowNodeLoadOptionsRequest.create({
          node_type: 'agent',
          field_name: 'model',
          credential_id: '',
        }),
      )) as WorkflowNodeLoadOptionsResponse;
      const opts = (resp?.options || []) as FieldOption[];
      cachedOptions = opts;
      return opts;
    } finally {
      inflight = null;
    }
  })();
  return inflight;
}

/** Display "openrouter/openai/gpt-4o-mini" → "gpt-4o-mini". */
function shortModelName(modelId: string): string {
  if (!modelId) return '';
  const parts = modelId.split('/');
  return parts[parts.length - 1];
}

function providerOf(opt: FieldOption): string | null {
  const meta = (opt.metadata || {}) as Record<string, unknown>;
  return typeof meta.provider === 'string' ? meta.provider : null;
}

/** Provider icon for this surface. PROVIDER_METADATA already holds compact
 *  markers for the CLI wrappers (OpenClaw's claw, Hermes' "H") rather than
 *  their full wordmarks, so we can use it directly with no per-surface override. */
function providerIconNode(provider: string | null): React.ReactNode | null {
  if (!provider) return null;
  return getProviderMetadata(provider as ModelProvider)?.icon ?? null;
}

export function AgentModelPicker({ selectedModelId, onSelect, openSignal }: AgentModelPickerProps) {
  const [options, setOptions] = useState<FieldOption[]>(() => cachedOptions ?? []);
  const [open, setOpen] = useState(false);
  // The modal renders over the full catalog (with capability filters etc.);
  // it consumes the same useModels() list the canvas agent node passes it.
  const { models } = useModels();

  // Eager prefetch on mount so the trigger shows the model's icon/name.
  useEffect(() => {
    if (cachedOptions) return;
    let cancelled = false;
    loadAgentModelOptions()
      .then(opts => { if (!cancelled) setOptions(opts); })
      .catch(err => console.warn('[AgentModelPicker] load failed', err));
    return () => { cancelled = true; };
  }, []);

  // Open the modal when the parent bumps openSignal (skip the initial 0).
  useEffect(() => {
    if (openSignal) setOpen(true);
  }, [openSignal]);

  const selectedOption = useMemo(
    () => options.find(o => o.value === selectedModelId) || null,
    [options, selectedModelId],
  );
  const selectedProvider = selectedOption ? providerOf(selectedOption) : null;
  const selectedIcon = providerIconNode(selectedProvider);
  const displayName = selectedOption?.label
    ? shortModelName(selectedOption.value)
    : shortModelName(selectedModelId) || 'Select model';

  const handleSelect = useCallback((value: string) => {
    onSelect(value);
    setOpen(false);
  }, [onSelect]);

  return (
    <>
      <button
        onClick={() => setOpen(true)}
        className="group flex items-center gap-2.5 -ml-1 px-2 py-1 rounded-lg hover:bg-foreground/[0.04] transition-colors"
        type="button"
      >
        {selectedIcon ? (
          <span className="w-8 h-8 shrink-0 flex items-center justify-center text-foreground/90 overflow-hidden">
            {selectedIcon}
          </span>
        ) : null}
        <span className="text-lg font-semibold text-foreground tracking-tight truncate max-w-[420px]">
          {displayName}
        </span>
        <ChevronDown className="w-4 h-4 text-muted-foreground dark:text-zinc-500 group-hover:text-foreground/80 transition-colors shrink-0" />
      </button>

      <ModelPickerModal
        open={open}
        onClose={() => setOpen(false)}
        onModelSelect={handleSelect}
        selectedModelId={selectedModelId}
        models={models || []}
        priorityModelIds={PRIORITY_MODELS}
      />
    </>
  );
}
