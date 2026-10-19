// Display mappings and formatters for usage data: subtype/category labels,
// badge accents, per-subtype rate footnotes, and UTC-safe day formatting.
// Subsumes the old lib/usage-utils.ts so every usage surface labels rows the
// same way.
import { formatUsd } from '~/lib/money';
import cliModels from '~/schemas/cli-models.json';
import usageNames from './usageNames.json';

/**
 * What a person reads for a charge: ONE table, usageNames.json, names every
 * subtype the backend records (`charges`), and families of them it records by
 * pattern (`families`: `prefix/*`, `*_suffix`, `{}` filled with what the star
 * matched). backend/tests/test_usage_subtype_names.py reads the code for every
 * subtype it can record and fails on one this table doesn't name. Model ids
 * are named by the model rule below.
 */
const CHARGE_NAMES: Record<string, string> = usageNames.charges;
const FAMILIES = Object.entries(usageNames.families as Record<string, string>).map(([pattern, label]) => ({
    re: new RegExp(`^${pattern.split('*').map((part) => part.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('(.+)')}$`),
    label,
}));

/** What a family's star matched, as words: "a100" → "A100", "build_cache" → "build cache". */
function starWords(text: string): string {
    if (/^(cpu|gpu|[a-z]\d[\w-]*)$/i.test(text)) return text.toUpperCase();
    return text.replace(/[_-]+/g, ' ');
}

function familyName(subtype: string): string | null {
    for (const { re, label } of FAMILIES) {
        const m = re.exec(subtype);
        if (!m) continue;
        const filled = label.replace('{}', starWords(m[1]));
        return filled.charAt(0).toUpperCase() + filled.slice(1);
    }
    return null;
}

/** A subtype no table names yet, still in words rather than its code: "storage/new_thing" → "New thing". */
function inWords(subtype: string): string {
    const last = subtype.split('/').pop() || subtype;
    const words = last.replace(/[_-]+/g, ' ').trim();
    return words ? words.charAt(0).toUpperCase() + words.slice(1) : subtype;
}

// Model ids name their maker ("anthropic/claude-sonnet-5-5"), start with a family name ("gpt-5.5"), or come through a
// router in front of a model ("openrouter/qwen/qwen3.7-plus"); anything else is some other kind of usage and keeps its
// own name.
const MODEL_GATEWAY = /^(openrouter|opencode|groq)\//;
// Claude Code's short names ("haiku") for the models they stand for.
const CLAUDE_ALIASES: Record<string, string> = cliModels.claude_code.aliases;
const MODEL_PROVIDERS = new Set(['anthropic', 'openai', 'google', 'gemini', 'x-ai', 'xai', 'meta-llama', 'mistralai', 'deepseek', 'qwen', 'moonshotai', 'z-ai', 'cohere', 'perplexity', 'amazon', 'microsoft', 'nvidia', 'minimax']);
const MODEL_FAMILY = /^(claude|gpt|o\d|gemini|gemma|llama|mistral|mixtral|codestral|ministral|grok|deepseek|qwen|kimi|glm|command|sonar|nova|phi|minimax)/;
// Words a model id lowercases that their makers don't.
const MODEL_WORDS: Record<string, string> = { deepseek: 'DeepSeek', glm: 'GLM', minimax: 'MiniMax', mimo: 'MiMo', oss: 'OSS' };

function modelWord(word: string, first: boolean): string {
    if (MODEL_WORDS[word]) return MODEL_WORDS[word];
    if (first && /^o\d/.test(word)) return word; // OpenAI's o-series stays lowercase
    if (/^(\d+(\.\d+)?[bmk]|[a-z]\d[\w.]*|x{0,2}[sml])$/.test(word)) return word.toUpperCase(); // 70B, K2, V3.1, A3B, XS
    if (/^\d/.test(word)) return word; // 5.5, 4o
    return word[0].toUpperCase() + word.slice(1);
}

/** A model id the way its maker writes the name ("anthropic/claude-sonnet-5-5" → "Claude Sonnet 5.5", "openai/gpt-5.5"
 *  → "GPT-5.5"), or null when the id isn't a model's. */
export function modelDisplayName(id: string): string | null {
    const full = id.split(':')[0].toLowerCase(); // ":free" and other routing variants
    const routed = MODEL_GATEWAY.test(full);
    const rest = full.replace(MODEL_GATEWAY, '');
    const slash = rest.indexOf('/');
    const provider = slash > 0 ? rest.slice(0, slash).replace(/^~/, '') : null; // "~openai": a router's moving alias
    const model = slash > 0 ? rest.slice(slash + 1) : rest;
    if (!model || (!routed && (provider ? !MODEL_PROVIDERS.has(provider) : !MODEL_FAMILY.test(model)))) return null;
    const words: string[] = [];
    for (const token of model.split('-')) {
        if (!token || /^\d{8}$/.test(token)) continue; // a release date
        const last = words[words.length - 1];
        // Version parts the id splits with hyphens ("claude-opus-4-1") rejoin with a dot.
        if (/^\d{1,2}$/.test(token) && last !== undefined && /^\d+(\.\d+)?$/.test(last)) words[words.length - 1] = `${last}.${token}`;
        else words.push(token);
    }
    if (!words.length) return null;
    // OpenAI hyphenates its brand onto the version: GPT-5.5, GPT-4o, GPT-OSS.
    const name =
        words[0] === 'gpt' && words.length > 1
            ? [`GPT-${modelWord(words[1], false)}`, ...words.slice(2).map((w) => modelWord(w, false))].join(' ')
            : words.map((w, i) => modelWord(w, i === 0)).join(' ');
    return provider === 'openrouter' ? `OpenRouter ${name}` : name; // the router's own picks, like openrouter/free
}

export const getDisplayName = (subtype: string): string => {
    // The builder's and test runs' versioned sentinels: the model behind them is NoClick's own.
    if (subtype.startsWith('noclick/builder')) return CHARGE_NAMES['noclick/builder-1'];
    if (subtype.startsWith('noclick/testing')) return CHARGE_NAMES['noclick/testing-1'];
    return CHARGE_NAMES[subtype] ?? familyName(subtype) ?? modelDisplayName(CLAUDE_ALIASES[subtype] ?? subtype) ?? inWords(subtype);
};

/** Human-readable label for the usage_type category column. */
export const USAGE_TYPE_LABEL: Record<string, string> = {
    ai_builder: 'AI Builder',
    ai_testing: 'Agent Testing',
    ai_usage: 'Agent / LLM',
    api_usage: 'Third-party API',
    cpu_usage: 'Compute (CPU)',
    gpu_usage: 'Compute (GPU)',
};

// Category chip colors live in theme.ts (usageTypeBadgeStyle), derived from
// RESOURCE_TYPE_COLORS so badges always match the charts.

/** Flat-rate footnotes shown in chart tooltips, keyed by raw usage_subtype.
 * agent/sandbox mirrors billing/pricing.py:SANDBOX_MINUTE_PRICE (0.05 credits a
 * minute) — update both together. */
export function subtypeRateNote(subtype: string): string | null {
    if (subtype === 'agent/sandbox') return `${formatUsd(0.05 * 60)} an hour of warm sandbox uptime`;
    return null;
}

/**
 * Format a backend day-bucket key ('YYYY-MM-DD', or 'YYYY-MM' for month
 * grouping) for display. The buckets are UTC days, so formatting MUST pin
 * timeZone to UTC — `new Date('2026-07-03')` parses as UTC midnight and a
 * local-time formatter shifts it a day back for viewers west of UTC.
 */
export function formatUtcDay(
    dateKey: string,
    opts?: { short?: boolean }
): string {
    const iso =
        dateKey.length === 7
            ? `${dateKey}-01T00:00:00Z`
            : `${dateKey}T00:00:00Z`;
    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) return dateKey;
    return date.toLocaleDateString('en-US', {
        month: opts?.short ? 'numeric' : 'short',
        day: 'numeric',
        timeZone: 'UTC',
    });
}
