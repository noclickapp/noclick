// What a person reads for a charge. ONE table, usageNames.json, names every kind of charge NoClick records
// (`charges`), the families of them it records by pattern (`families`: `prefix/*`, `*_suffix`, `{}` filled with what
// the star matched), and the services charges add up to (`services`). NoClick's backend checks every kind it can
// record against this table. Model ids are named by the model rule below.
import usageNames from './usageNames.json';

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

let modelAliases: Record<string, string> = {};

/** The short names a coding agent records its models by ("sonnet"), each with the model id it stands for. A host
 *  that knows them says so once, before a charge is named; without them a short name reads as its own words. */
export function setModelAliases(aliases: Record<string, string>): void {
    modelAliases = aliases;
}

/** A charge's kind (its `usage_subtype`) as a person reads it. */
export function chargeName(subtype: string): string {
    // The builder's and test runs' versioned sentinels: the model behind them is NoClick's own.
    if (subtype.startsWith('noclick/builder')) return CHARGE_NAMES['noclick/builder-1'];
    if (subtype.startsWith('noclick/testing')) return CHARGE_NAMES['noclick/testing-1'];
    return CHARGE_NAMES[subtype] ?? familyName(subtype) ?? modelDisplayName(modelAliases[subtype] ?? subtype) ?? inWords(subtype);
}
