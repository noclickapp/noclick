// Maps free-form node-palette search queries (e.g. "claude code", "codex",
// "opus", "gpt-5.2", "hermes", "deepseek r1") to an initial config seed for
// the Agent node, and tells the palette filter whether (and how strongly) the
// query targets the agent node.
//
// The matcher is built so we don't have to hand-maintain alias tables:
//  • Per-CLI aliases are derived from the CLI's model string (kebab/space/
//    no-dash variants + first segment).
//  • Sub-model aliases come from backend/nodes/agent/config/_cli_models.json,
//    which CI refreshes daily — new Codex models appear here automatically.
//  • Free-form model queries (things not in the CLI alias set) are matched
//    against the live model catalog via useModels(), with OpenRouter models
//    preferred and the model's `created` epoch breaking ties so the newest
//    Claude/GPT/Gemini wins for a bare "claude" / "gpt" / "gemini".
//  • Failing all of that, one typo in a harness name is forgiven ("cloude",
//    "clude code"), flagged `typo` so the palette ranks it under literal hits.
//
// Used by NodesTabContent (to surface the Agent tile on CLI/model queries) and
// by the drag-drop + click-to-add paths (to seed data.config.model and the
// matching CLI-specific sub-model field on the freshly created node).

import type { Model } from '~/types/model';
import { seedWrapperSubmodel } from '~/lib/agentCredentialModel';
// `cli-models.json` mirrors backend/nodes/agent/config/_cli_models.json
// (auto-refreshed daily by .github/workflows/refresh-cli-models.yml; synced
// into app/schemas by scripts/generate_socket_types.py on every commit) —
// its codex `models` array and claude_code `aliases` map are the source of
// truth for sub-model lists.
import cliModelsJson from '~/schemas/cli-models.json';

// Irreducible per-CLI metadata. `model` and `subField` mirror the Pydantic
// configs in backend/nodes/agent/config/* — they're the canonical contract
// for what gets written into data.config when the agent runs the given CLI.
interface CliAgentSpec {
    /** Key into _cli_models.json (the file's top-level block name). */
    jsonKey: 'codex' | 'claude_code' | 'hermes_agent';
    /** Value written to data.config.model — what infer_model_type matches on. */
    model: string;
    /** CLI-specific sub-model field on AgentConfig (claude_code_model, etc.). */
    subField: string;
    /** Human aliases the matcher can't derive from `model` (memes, brand names). */
    synonyms: string[];
}

const CLI_AGENT_SPECS: CliAgentSpec[] = [
    { jsonKey: 'claude_code',  model: 'claude-code',  subField: 'claude_code_model',  synonyms: ['clawd', 'anthropic'] },
    { jsonKey: 'codex',        model: 'codex',        subField: 'codex_model',        synonyms: ['openai codex'] },
    // OpenCode and HermesAgent aren't in _cli_models.json yet; aliases derive
    // from `model` and the synonyms list keeps brand/community shorthand.
    { jsonKey: 'hermes_agent', model: 'hermes', subField: 'hermes_agent_model', synonyms: ['hermes agent', 'nous', 'nousresearch', 'nous research'] },
];

// Standalone (no JSON block) — kept in a separate list so the spec table stays
// purely "lives in _cli_models.json". Same shape, just no sub-aliases.
const STANDALONE_CLI_SPECS: Omit<CliAgentSpec, 'jsonKey'>[] = [
    { model: 'opencode', subField: 'opencode_model', synonyms: ['open code', 'open-code'] },
    { model: 'openclaw', subField: 'openclaw_model', synonyms: ['open claw', 'open-claw', 'openclaw cli', 'openclaw agent'] },
];

// Canonical harness → config contract, keyed by backend `model_type` (the
// Pydantic discriminator). `model` is what we write into data.config.model;
// the backend's infer_model_type() maps it back to this model_type, and
// `subField` is the CLI-specific sub-model field. Derived from the spec tables
// above so this stays a single source of truth — the /agents marketing pages
// and agentScaffold consume it instead of re-listing the harness contract.
// (CliAgentSpec.jsonKey IS the model_type for codex/claude_code/hermes_agent;
//  the standalone CLIs use their model id as the model_type: opencode/openclaw.)
export interface HarnessModelSpec {
    /** Backend model_type discriminator (e.g. "claude_code"). */
    modelType: string;
    /** Value written to data.config.model (e.g. "claude-code"). */
    model: string;
    /** CLI-specific sub-model field on AgentConfig (e.g. "claude_code_model"). */
    subField: string;
}

export const HARNESS_MODEL_SPECS: Record<string, HarnessModelSpec> = (() => {
    const out: Record<string, HarnessModelSpec> = {};
    for (const s of CLI_AGENT_SPECS) {
        out[s.jsonKey] = { modelType: s.jsonKey, model: s.model, subField: s.subField };
    }
    for (const s of STANDALONE_CLI_SPECS) {
        out[s.model] = { modelType: s.model, model: s.model, subField: s.subField };
    }
    return out;
})();

const MIN_PREFIX_CHARS = 3;
// "cl"/"clo" are one edit from too many unrelated words to forgive a typo in.
const MIN_TYPO_CHARS = 4;

// Derive base CLI aliases from a kebab-cased model id. "claude-code" yields
// ["claude-code", "claude code", "claudecode", "claude"]. New CLI rename in
// backend Pydantic propagates here automatically.
function deriveBaseAliases(model: string): string[] {
    const lower = model.toLowerCase();
    const aliases = new Set<string>([lower]);
    aliases.add(lower.replace(/-/g, ' '));
    aliases.add(lower.replace(/-/g, ''));
    const firstSeg = lower.split(/[-/]/)[0];
    if (firstSeg && firstSeg.length >= 3) aliases.add(firstSeg);
    return Array.from(aliases);
}

// Pull sub-model aliases from _cli_models.json. Each block exposes either
// a `models` array (codex) or an `aliases` object (claude_code) — both are
// flattened to "alias key" → "value to write into the sub-field".
function deriveSubAliases(jsonKey: CliAgentSpec['jsonKey']): Record<string, string> {
    const block = (cliModelsJson as Record<string, any>)[jsonKey];
    const out: Record<string, string> = {};
    if (!block) return out;
    if (Array.isArray(block.models)) {
        for (const m of block.models) {
            const s = String(m);
            out[s.toLowerCase()] = s;
        }
    }
    if (block.aliases && typeof block.aliases === 'object') {
        for (const key of Object.keys(block.aliases)) {
            out[key.toLowerCase()] = key;
        }
    }
    return out;
}

// Flat alias index built once at module load. Each entry is either a CLI-level
// alias (selects the CLI, no sub-model) or a sub-model alias (selects the CLI
// AND pre-fills its sub-model field).
interface IndexEntry {
    alias: string;
    spec: { model: string; subField: string };
    subValue?: string;
}

const CLI_INDEX: IndexEntry[] = (() => {
    const entries: IndexEntry[] = [];
    const push = (alias: string, spec: { model: string; subField: string }, subValue?: string) => {
        if (!alias) return;
        entries.push({ alias: alias.toLowerCase(), spec, subValue });
    };
    for (const spec of CLI_AGENT_SPECS) {
        for (const a of deriveBaseAliases(spec.model)) push(a, spec);
        for (const s of spec.synonyms) push(s, spec);
        for (const [alias, value] of Object.entries(deriveSubAliases(spec.jsonKey))) push(alias, spec, value);
    }
    for (const spec of STANDALONE_CLI_SPECS) {
        for (const a of deriveBaseAliases(spec.model)) push(a, spec);
        for (const s of spec.synonyms) push(s, spec);
    }
    return entries;
})();

// Substring matches dominate prefix matches by a large constant so a confident
// hit ("claude code") is never displaced by a partial one ("claud"). Within
// each class, longer matches win on substring, more-typed-chars/shorter alias
// on prefix.
function scoreAlias(alias: string, q: string): number {
    if (q.includes(alias)) return 100_000 + alias.length;
    if (q.length >= MIN_PREFIX_CHARS && alias.startsWith(q)) return q.length * 100 - alias.length;
    return -1;
}

interface AgentSeed {
    model: string;
    subField?: string;
    subValue?: string;
}

function resolveCliSeed(q: string): AgentSeed | null {
    let bestCli: { spec: IndexEntry['spec']; score: number } | null = null;
    let bestSub: { spec: IndexEntry['spec']; subValue: string; score: number } | null = null;

    for (const entry of CLI_INDEX) {
        const score = scoreAlias(entry.alias, q);
        if (score < 0) continue;
        if (entry.subValue !== undefined) {
            if (!bestSub || score > bestSub.score) bestSub = { spec: entry.spec, subValue: entry.subValue, score };
        } else {
            if (!bestCli || score > bestCli.score) bestCli = { spec: entry.spec, score };
        }
    }

    const chosen = bestCli?.spec ?? bestSub?.spec;
    if (!chosen) return null;
    const seed: AgentSeed = { model: chosen.model };
    if (bestSub && bestSub.spec.model === chosen.model) {
        seed.subField = chosen.subField;
        seed.subValue = bestSub.subValue;
    }
    return seed;
}

// Fewest edits turning `q` into some prefix of `alias`, where swapping two
// neighbouring letters counts as one edit: "cloude" → "claude",
// "clou" → "clau" and "cladu" → "claud" are each 1.
function prefixEditDistance(q: string, alias: string): number {
    let before: number[] = [];
    let prev = Array.from({ length: alias.length + 1 }, (_, j) => j);
    for (let i = 1; i <= q.length; i++) {
        const row = [i];
        for (let j = 1; j <= alias.length; j++) {
            let d = Math.min(
                prev[j] + 1,
                row[j - 1] + 1,
                prev[j - 1] + (q[i - 1] === alias[j - 1] ? 0 : 1)
            );
            if (
                i > 1 &&
                j > 1 &&
                q[i - 1] === alias[j - 2] &&
                q[i - 2] === alias[j - 1]
            )
                d = Math.min(d, before[j - 2] + 1);
            row.push(d);
        }
        before = prev;
        prev = row;
    }
    return Math.min(...prev);
}

// A harness name typed with one typo. Only harness-level aliases are forgiven
// (sub-model aliases are a daily-refreshed list of generic words), and the
// first letter must match: "node"/"term" are one edit from "code"/"herm" too.
function resolveTypoSeed(q: string): AgentSeed | null {
    if (q.length < MIN_TYPO_CHARS) return null;
    const hit = CLI_INDEX.find(
        (e) =>
            e.subValue === undefined &&
            e.alias[0] === q[0] &&
            prefixEditDistance(q, e.alias) <= 1
    );
    return hit ? { model: hit.spec.model } : null;
}

// Match tier — lower number = stronger match. Matters more than score length
// when picking the winner, so a model whose tail starts with the query always
// beats one that merely contains it somewhere.
//
//   tier 0: openrouter-tail starts with query (e.g. q="minimax" vs "minimax/minimax-m2.7")
//   tier 1: openrouter-tail contains query anywhere
//   tier 2: full id contains query (only the "openrouter/" prefix matched)
//
// Within a tier we intentionally do NOT penalize id length — that was the bug
// that made "minimax-m2" beat "minimax-m2.7". Length-ties are then broken by
// `created` desc, so the newest matching model wins for free-form queries.
interface CatalogMatch { tier: 0 | 1 | 2; len: number }

function matchModel(id: string, q: string): CatalogMatch | null {
    if (q.length < MIN_PREFIX_CHARS) return null;
    const lowerId = id.toLowerCase();
    const tail = lowerId.replace(/^openrouter\//, '');
    if (tail.startsWith(q)) return { tier: 0, len: q.length };
    if (tail.includes(q))   return { tier: 1, len: q.length };
    if (lowerId.includes(q)) return { tier: 2, len: q.length };
    return null;
}

// Spaces vs dashes are interchangeable in model slugs ("claude opus" should
// hit "claude-opus-4-7"). Normalize the query the same way OpenRouter ids
// canonicalize on dashes. Empty whitespace runs collapse so "claude  opus"
// also works.
function normalizeCatalogQuery(q: string): string {
    return q.trim().toLowerCase().replace(/\s+/g, '-');
}

// Free-form catalog match. Only OpenRouter models compete (per design — other
// providers aren't weighted). Tier first, then `created` desc so the newest
// model wins a tier-tie (the "minimax m2.7 beats minimax m2" case).
function resolveCatalogSeed(q: string, models: Model[] | undefined): AgentSeed | null {
    if (!models || models.length === 0) return null;
    const nq = normalizeCatalogQuery(q);
    if (!nq) return null;
    let best: { id: string; tier: number; len: number; created: number } | null = null;
    for (const m of models) {
        const source = (m as Model & { source?: string }).source;
        if (source && source !== 'openrouter') continue;
        const match = matchModel(m.id, nq);
        if (!match) continue;
        const created = m.created ?? 0;
        if (
            !best
            || match.tier < best.tier
            || (match.tier === best.tier && match.len > best.len)
            || (match.tier === best.tier && match.len === best.len && created > best.created)
        ) {
            best = { id: m.id, tier: match.tier, len: match.len, created };
        }
    }
    return best ? { model: best.id } : null;
}

export interface AgentQueryMatch {
    /** data.config seed for the Agent node added with this query. */
    config: Record<string, unknown>;
    /** Matched only by forgiving a typo in a harness name: a weaker signal than
     *  any literal node-name match, so the palette must rank it below them. */
    typo: boolean;
}

// Whether the palette search targets the Agent node, and the config seed to
// apply when it's added. CLI agents win when their alias matches; otherwise a
// live catalog match; otherwise a one-typo harness match. Null when nothing
// matches — the caller leaves the agent tile out and its config alone.
export function matchAgentQuery(
    query: string,
    models?: Model[]
): AgentQueryMatch | null {
    const q = query.trim().toLowerCase();
    if (!q) return null;
    const exact = resolveCliSeed(q) ?? resolveCatalogSeed(q, models);
    const seed = exact ?? resolveTypoSeed(q);
    if (!seed) return null;
    const config: Record<string, unknown> = { model: seed.model };
    if (seed.subField && seed.subValue) config[seed.subField] = seed.subValue;
    // Seed a wrapper harness's default sub-model when the search didn't pin a
    // specific one (e.g. bare "openclaw"), so the dropped node isn't left with
    // an empty sub-model (no-op for regular models / already-seeded sub-models).
    return {
        config: { ...config, ...seedWrapperSubmodel(seed.model, config) },
        typo: !exact,
    };
}

// Human-readable summary of an agent seed, e.g. "claude-code · opus" or
// "MiniMax M2.7". When `models` is provided and contains the matched id, the
// catalog's `name` field is used (e.g. "Claude Opus 4.7") so the tile shows a
// friendly label instead of the verbose "openrouter/<provider>/<slug>" id —
// otherwise we strip the "openrouter/" prefix for compactness.
export function describeAgentSeed(
    config: Record<string, any> | null | undefined,
    models?: Model[],
): string | null {
    const modelId = config?.model;
    if (!modelId || typeof modelId !== 'string') return null;
    const fromCatalog = models?.find((m) => m.id === modelId);
    const friendly = fromCatalog?.name ?? modelId.replace(/^openrouter\//, '');
    const sub =
        config?.claude_code_model ||
        config?.codex_model ||
        config?.opencode_model ||
        config?.openclaw_model ||
        config?.hermes_agent_model;
    return sub ? `${friendly} · ${sub}` : friendly;
}
