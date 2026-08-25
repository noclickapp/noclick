// Public builder input bridge page (/b/{linkId}): anyone holding the link can
// answer a parked builder run's questions / connect requested credentials
// without a NoClick account — the capability model of credential.provide,
// applied to builder <ask/>s. Deliberately mirrors BuilderInputDrawer's
// wizard UX (step dots, one question at a time, dot-radio selections with
// "Other", the same footer button) — it IS the same ask, rendered publicly.
import { useCallback, useEffect, useRef, useState } from 'react';
import type { MetaFunction } from 'react-router';
import { useParams } from 'react-router';
import { ArrowRight, Check, CheckCircle2, ChevronLeft, ExternalLink, Loader2 } from 'lucide-react';
import { cn } from '~/lib/utils';
import { buildSeoMeta } from '~/lib/seo';
import { PoweredByBadge } from '~/components/agent-share/PoweredByBadge';
import { PublicThemeToggle } from '~/components/shared/PublicThemeToggle';
import { CredentialProvideFlow } from '~/components/credential/CredentialProvideFlow';
import { CredentialCreateEntryButton } from '~/components/credential/CredentialCreateEntryButton';
import { EnvVarRowsEditor, emptyEnvRow } from '~/components/workflow/EnvVarRowsEditor';
import { rowsToEnv, type EnvRow } from '~/components/workflow/agentEnvVars';

export const meta: MetaFunction = () =>
  buildSeoMeta({
    title: 'Answer Builder Questions - NoClick',
    description: 'Provide the details a NoClick workflow build is waiting on.',
    indexable: false,
  });

const API_BASE = typeof window !== 'undefined'
  ? ((window as unknown as { ENV?: { API_URL?: string } }).ENV?.API_URL || import.meta.env.VITE_API_URL || '')
  : (process.env.API_URL || '');

interface BridgeInput {
  id: string;
  label: string;
  description?: string;
  required: boolean;
  type: 'text' | 'config' | 'selection' | 'credential' | 'env';
  options?: ({ label?: string; value?: string; id?: string } | string)[];
  /** Multi-select selection ask (from <ask multiple="true">): checkboxes, answer comma-joined. */
  multiple?: boolean;
  defaultValue?: string;
  credential_type?: string;
  credential_provide_url?: string;
  credential_provide_token?: string;
  credential_fulfilled?: boolean;
  /** Sandbox env-var names to collect (type === 'env'). snake_case, from the
   *  public GET projection. */
  env_keys?: { name: string; description?: string }[];
}

interface BridgePayload {
  workflow_name: string;
  expires_at: string;
  inputs: BridgeInput[];
}

const OTHER = '__other__';

/** "google_sheets_oauth" → "Google Sheets" — the raw credential_type slug is
 *  an internal id, never UI text. */
function credentialLabel(type?: string): string {
  if (!type) return 'account';
  return type
    .replace(/_oauth$/, '')
    .split('_')
    .map(w => (w ? w.charAt(0).toUpperCase() + w.slice(1) : w))
    .join(' ');
}

function optValue(opt: BridgeInput['options'] extends (infer T)[] | undefined ? T : never): string {
  return typeof opt === 'string' ? opt : (opt.value ?? opt.id ?? opt.label ?? '');
}

function optLabel(opt: BridgeInput['options'] extends (infer T)[] | undefined ? T : never): string {
  return typeof opt === 'string' ? opt : (opt.label ?? opt.value ?? '');
}

/** Option list, cloned from the drawer's SelectionInput — including the
 *  "Other" row that expands into an inline text input. Dot-radios by default;
 *  `input.multiple` renders toggling checkboxes instead (multi-select). */
function SelectionInput({
  input, value, otherText, onPick, onOtherText, multiSelected, onToggle,
}: {
  input: BridgeInput;
  value: string;
  otherText: string;
  onPick: (v: string) => void;
  onOtherText: (t: string) => void;
  /** Multi-select state (input.multiple): chosen option values, OTHER included when checked. */
  multiSelected: string[];
  onToggle: (v: string) => void;
}) {
  const multiple = !!input.multiple;
  const isOther = multiple ? multiSelected.includes(OTHER) : value === OTHER;
  const otherRef = useRef<HTMLInputElement>(null);
  useEffect(() => { if (isOther) otherRef.current?.focus(); }, [isOther]);

  // Checkbox square for multi, radio dot for single — the affordance that
  // tells the visitor whether several options can be picked.
  const indicator = (selected: boolean) => multiple ? (
    <div className={cn(
      'w-3.5 h-3.5 rounded-[4px] border-2 shrink-0 flex items-center justify-center',
      selected ? 'border-foreground bg-foreground' : 'border-foreground/30',
    )}>
      {selected && <Check className="w-2.5 h-2.5 text-background" strokeWidth={3} />}
    </div>
  ) : (
    <div className={cn(
      'w-3 h-3 rounded-full border-2 shrink-0',
      selected ? 'border-foreground bg-foreground' : 'border-foreground/30',
    )} />
  );

  return (
    <div className="space-y-1.5">
      {multiple && (
        <p className="text-[11px] text-muted-foreground dark:text-zinc-500">Select all that apply</p>
      )}
      {(input.options ?? []).map((opt, i) => {
        const v = optValue(opt);
        const selected = multiple ? multiSelected.includes(v) : (value === v && !isOther);
        return (
          <button
            key={i}
            type="button"
            onClick={() => (multiple ? onToggle(v) : onPick(v))}
            className={cn(
              'w-full flex items-center gap-2 px-3 py-2 rounded-lg border text-left text-sm outline-none transition-colors',
              selected
                ? 'border-foreground/30 bg-foreground/10 text-foreground'
                : 'border-border dark:border-white/[0.06] bg-foreground/[0.02] text-muted-foreground dark:text-white/60 hover:bg-foreground/[0.05] hover:border-foreground/10',
            )}
          >
            {indicator(selected)}
            {optLabel(opt)}
          </button>
        );
      })}
      <button
        type="button"
        onClick={() => { if (multiple) onToggle(OTHER); else if (!isOther) onPick(OTHER); }}
        className={cn(
          'w-full flex items-center gap-2 px-3 py-2 rounded-lg border text-left text-sm outline-none transition-colors',
          isOther
            ? 'border-foreground/30 bg-foreground/10 text-foreground'
            : 'border-border dark:border-white/[0.06] bg-foreground/[0.02] text-muted-foreground dark:text-white/60 hover:bg-foreground/[0.05] hover:border-foreground/10',
        )}
      >
        {indicator(isOther)}
        {isOther ? (
          <input
            ref={otherRef}
            type="text"
            value={otherText}
            onChange={e => onOtherText(e.target.value)}
            onClick={e => e.stopPropagation()}
            placeholder="Type your answer"
            className="flex-1 bg-transparent text-foreground text-sm outline-none placeholder:text-muted-foreground/50"
          />
        ) : 'Other'}
      </button>
    </div>
  );
}

export default function BuilderBridgePage() {
  const { linkId } = useParams();
  const [payload, setPayload] = useState<BridgePayload | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [values, setValues] = useState<Record<string, string>>({});
  const [otherTexts, setOtherTexts] = useState<Record<string, string>>({});
  // Multi-select inputs: chosen option values per input id (OTHER sentinel
  // included when the "Other" row is checked; its text lives in otherTexts).
  const [multiSel, setMultiSel] = useState<Record<string, string[]>>({});
  // Env inputs collect a {NAME: value} bundle, not a scalar — kept as editor rows
  // per input id, folded into the submit payload as an object.
  const [envRows, setEnvRows] = useState<Record<string, EnvRow[]>>({});
  const [step, setStep] = useState(0);
  const [submitting, setSubmitting] = useState(false);
  const [submitted, setSubmitted] = useState(false);

  const load = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/builder-bridge/${linkId}`);
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        throw new Error(body?.detail || 'This link is invalid, answered, or expired.');
      }
      const data: BridgePayload = await res.json();
      setPayload(data);
      setValues(v => {
        const next = { ...v };
        for (const inp of data.inputs) {
          if (next[inp.id] === undefined && inp.defaultValue) next[inp.id] = inp.defaultValue;
        }
        return next;
      });
      setLoadError(null);
    } catch (e) {
      setLoadError(e instanceof Error ? e.message : 'Failed to load this link.');
    }
  }, [linkId]);

  useEffect(() => { void load(); }, [load]);

  const inputs = payload?.inputs ?? [];
  const current = inputs[step];
  const isLast = step === inputs.length - 1;

  // Returning from the provide tab: poll fulfillment while the current step is
  // an unconnected credential, so the "Connected" state appears on its own.
  useEffect(() => {
    if (!current || current.type !== 'credential' || current.credential_fulfilled) return;
    const timer = setInterval(() => { void load(); }, 4000);
    return () => clearInterval(timer);
  }, [current, load]);

  const answerOf = (inp: BridgeInput): string => {
    if (inp.multiple && inp.type === 'selection') {
      const sel = multiSel[inp.id] ?? [];
      const parts = sel.filter(v => v !== OTHER);
      const other = sel.includes(OTHER) ? (otherTexts[inp.id] ?? '').trim() : '';
      if (other) parts.push(other);
      return parts.join(', ');
    }
    const v = values[inp.id] ?? '';
    return v === OTHER ? (otherTexts[inp.id] ?? '').trim() : v.trim();
  };

  // The {NAME: value} bundle for an env input, or null if it isn't validly
  // fillable yet (blank/dup/reserved name). Never throws — rowsToEnv does.
  const envBundleOf = (inp: BridgeInput): Record<string, string> | null => {
    if (inp.type !== 'env') return null;
    try {
      const env = rowsToEnv(envRows[inp.id] ?? []);
      return Object.keys(env).length ? env : null;
    } catch {
      return null;
    }
  };

  const filled = (inp: BridgeInput): boolean =>
    inp.type === 'credential'
      ? !!inp.credential_fulfilled
      : inp.type === 'env'
        ? !!envBundleOf(inp)
        : !!answerOf(inp);

  const canAdvance = !!current && (!current.required || filled(current));

  const submit = useCallback(async () => {
    setSubmitting(true);
    setSubmitError(null);
    try {
      const out: Record<string, string | Record<string, string>> = {};
      for (const inp of inputs) {
        if (inp.type === 'env') {
          // Raw {NAME: value} — the server mints an agent_env credential from it
          // and never stores the values in the graph.
          const bundle = envBundleOf(inp);
          if (bundle) out[inp.id] = bundle;
          continue;
        }
        const v = answerOf(inp);
        if (v) out[inp.id] = v;
      }
      const res = await fetch(`${API_BASE}/api/builder-bridge/${linkId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ values: out }),
      });
      const body = await res.json().catch(() => null);
      if (!res.ok) throw new Error(body?.detail || 'Submission failed — try again.');
      setSubmitted(true);
    } catch (e) {
      setSubmitError(e instanceof Error ? e.message : 'Submission failed — try again.');
      void load();
    } finally {
      setSubmitting(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [linkId, inputs, values, otherTexts, multiSel, load]);

  // Re-open a fulfilled credential input (test token → real one): the backend
  // rotates the request and the reload renders the connect UI again.
  const reconnect = useCallback(async (inputId: string) => {
    try {
      await fetch(`${API_BASE}/api/builder-bridge/${linkId}/reconnect`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ input_id: inputId }),
      });
    } finally {
      void load();
    }
  }, [linkId, load]);

  const handleNext = () => {
    if (!isLast) { setStep(s => s + 1); return; }
    void submit();
  };

  // Drawer skip semantics: mid-wizard just advances (answer left empty); on
  // the last step submit the partial answers — the builder re-asks for what
  // it still needs. An all-empty skip has nothing to send.
  const handleSkip = () => {
    if (!isLast) { setStep(s => s + 1); return; }
    if (inputs.some(filled)) { void submit(); return; }
    setSubmitError('Answer at least one question before sending.');
  };

  return (
    <div className="min-h-dvh bg-background text-foreground flex flex-col items-center px-4 py-12">
      <PublicThemeToggle />
      <div className="w-full max-w-md flex flex-col">
        {/* Page header — the share-page idiom: micro-label + identity. */}
        <div className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground dark:text-zinc-500">
          Workflow builder
        </div>
        <h1 className="mt-1.5 text-lg font-semibold tracking-tight">
          {payload ? `Building “${payload.workflow_name}”` : 'Builder questions'}
        </h1>
        <p className="mt-1 text-[13px] leading-relaxed text-muted-foreground dark:text-zinc-500">
          Whoever sent you this link is building an automation on NoClick and
          the builder needs a few answers to continue. No account needed.
        </p>

        {/* Card — the drawer, rendered as a page. */}
        <div className="mt-6 rounded-2xl border border-border bg-card overflow-hidden" data-testid="bridge-card">
          {submitted ? (
            <div className="px-6 py-10 text-center" data-testid="bridge-submitted">
              <CheckCircle2 className="mx-auto h-7 w-7 text-emerald-500" />
              <div className="mt-3 text-sm font-semibold">Answers sent</div>
              <p className="mt-1 text-[13px] text-muted-foreground dark:text-zinc-500">
                The builder is continuing with your answers. You can close this page.
              </p>
            </div>
          ) : loadError ? (
            <div className="px-5 py-6 text-sm text-muted-foreground" data-testid="bridge-error">
              {loadError}
            </div>
          ) : !payload || !current ? (
            <div className="flex items-center justify-center gap-2 px-5 py-10 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" /> Loading…
            </div>
          ) : (
            <>
              {/* Header: title row + step dots (drawer clone). */}
              <div className="px-4 pt-4 pb-2">
                <div className="flex items-center justify-between">
                  <h3 className="text-sm font-semibold text-foreground">Setup required</h3>
                  <div className="flex items-center gap-3">
                    {step > 0 && (
                      <button
                        type="button"
                        onClick={() => setStep(s => s - 1)}
                        className="flex items-center gap-0.5 text-xs text-muted-foreground dark:text-zinc-500 hover:text-foreground transition-colors"
                      >
                        <ChevronLeft className="w-3.5 h-3.5" />
                        Back
                      </button>
                    )}
                    <button
                      type="button"
                      onClick={handleSkip}
                      data-testid="bridge-skip"
                      className="text-xs text-muted-foreground dark:text-zinc-500 hover:text-foreground transition-colors"
                    >
                      Skip
                    </button>
                  </div>
                </div>
                <div className="flex items-center gap-1.5 mt-2">
                  {inputs.map((inp, i) => (
                    <div
                      key={inp.id}
                      className={cn(
                        'w-1.5 h-1.5 rounded-full transition-all',
                        i === step
                          ? 'bg-foreground w-3'
                          : filled(inp)
                            ? 'bg-emerald-500'
                            : 'bg-muted-foreground/50 dark:bg-zinc-600',
                      )}
                    />
                  ))}
                  <span className="text-xs text-muted-foreground dark:text-zinc-500 ml-1">
                    Step {step + 1} of {inputs.length}
                  </span>
                </div>
              </div>

              {/* Current question. */}
              <div className="px-4 py-3">
                <div className="mb-3">
                  <div className="flex items-center gap-2">
                    <span className="text-[13px] font-medium text-foreground">
                      {current.label}
                      {current.required && <span className="text-red-600 dark:text-red-400 ml-1">*</span>}
                    </span>
                    {filled(current) && <CheckCircle2 className="w-3.5 h-3.5 text-emerald-500 shrink-0" />}
                  </div>
                  {current.description && (
                    <p className="text-xs text-muted-foreground mt-1">{current.description}</p>
                  )}
                </div>

                {current.type === 'credential' ? (
                  current.credential_fulfilled ? (
                    <div className="space-y-2">
                      <div className="flex items-center gap-2 px-3 py-2 rounded-lg border border-emerald-500/30 bg-emerald-500/[0.06] text-sm text-emerald-600 dark:text-emerald-400">
                        <CheckCircle2 className="h-4 w-4" /> Connected
                      </div>
                      {/* The app's bordered entry-point button (shared with
                          NodeCredentials' Create-new) — a text link was too
                          easy to miss next to the Connected chip. */}
                      <div data-testid="bridge-reconnect">
                        <CredentialCreateEntryButton
                          label="Connect a different account"
                          onClick={() => void reconnect(current.id)}
                        />
                      </div>
                    </div>
                  ) : current.credential_provide_token ? (
                    // The REAL connect experience — the same method-kind
                    // registry and OAuth/QR components the logged-in drawer
                    // uses, in 'ask' variant so it reads as the drawer's
                    // credential step (app tokens, no provide-page chrome).
                    <CredentialProvideFlow
                      token={current.credential_provide_token}
                      apiBase={API_BASE}
                      compact
                      onProvided={() => void load()}
                    />
                  ) : current.credential_provide_url ? (
                    // Legacy links minted before the inline flow: new-tab fallback.
                    <a
                      href={current.credential_provide_url}
                      target="_blank"
                      rel="noreferrer"
                      className="w-full flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg border border-border dark:border-white/[0.08] bg-foreground/[0.02] text-sm text-foreground/80 hover:bg-foreground/[0.05] hover:border-foreground/[0.15] transition-all"
                    >
                      Connect {credentialLabel(current.credential_type)}
                      <ExternalLink className="w-3.5 h-3.5" />
                    </a>
                  ) : (
                    <p className="text-[13px] text-muted-foreground">
                      This connection can&rsquo;t be completed from this link — use
                      Skip and the builder will follow up.
                    </p>
                  )
                ) : current.type === 'selection' && current.options?.length ? (
                  <SelectionInput
                    input={current}
                    value={values[current.id] ?? ''}
                    otherText={otherTexts[current.id] ?? ''}
                    onPick={v => setValues(prev => ({ ...prev, [current.id]: v }))}
                    onOtherText={t => setOtherTexts(prev => ({ ...prev, [current.id]: t }))}
                    multiSelected={multiSel[current.id] ?? []}
                    onToggle={v => setMultiSel(prev => {
                      const sel = prev[current.id] ?? [];
                      return {
                        ...prev,
                        [current.id]: sel.includes(v) ? sel.filter(s => s !== v) : [...sel, v],
                      };
                    })}
                  />
                ) : current.type === 'env' ? (
                  <div className="space-y-1.5">
                    <EnvVarRowsEditor
                      rows={
                        envRows[current.id] ??
                        ((current.env_keys?.length
                          ? current.env_keys.map(k => ({ key: k.name, value: '' }))
                          : [emptyEnvRow()]))
                      }
                      onChange={rows => setEnvRows(prev => ({ ...prev, [current.id]: rows }))}
                      lockKeys={!!current.env_keys?.length}
                    />
                    <p className="text-[11px] text-muted-foreground">
                      Values are encrypted and used only inside the agent&rsquo;s sandbox.
                    </p>
                  </div>
                ) : (
                  <input
                    type="text"
                    value={values[current.id] ?? ''}
                    onChange={e => setValues(prev => ({ ...prev, [current.id]: e.target.value }))}
                    onKeyDown={e => { if (e.key === 'Enter' && canAdvance) handleNext(); }}
                    placeholder="Type your answer"
                    data-testid={`bridge-input-${current.id}`}
                    className="w-full px-3 py-2 rounded-lg border border-border dark:border-white/[0.06] bg-foreground/[0.02] text-sm text-foreground outline-none transition-colors focus:border-foreground/20 placeholder:text-muted-foreground/50"
                  />
                )}

                {submitError && (
                  <div className="mt-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-[13px] text-red-600 dark:border-red-900/40 dark:bg-red-950/30 dark:text-red-400">
                    {submitError}
                  </div>
                )}
              </div>

              {/* Footer (drawer clone). */}
              <div className="px-4 py-3 border-t border-foreground/[0.06] flex items-center gap-2">
                <button
                  type="button"
                  onClick={handleNext}
                  disabled={!canAdvance || submitting}
                  data-testid="bridge-next"
                  className={cn(
                    'flex-1 flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl text-sm font-medium transition-all',
                    canAdvance && !submitting
                      ? 'bg-primary text-primary-foreground hover:bg-primary/90 cursor-pointer'
                      : 'bg-foreground/10 text-foreground/40 cursor-not-allowed',
                  )}
                >
                  {submitting ? 'Sending…' : isLast ? 'Send answers' : 'Next'}
                  {!submitting && <ArrowRight className="w-4 h-4" />}
                </button>
              </div>
            </>
          )}
        </div>

        <div className="mt-6 flex justify-center">
          <PoweredByBadge />
        </div>
      </div>
    </div>
  );
}
