// Regenerates the machine-written GENERATED section of app/data/toolPresets.ts:
// heuristic "everyday" + "read-only" presets for every pair-page provider that
// has no hand-curated entry, derived from the generated node schemas (reads +
// common safe act verbs; destructive and plumbing ops excluded). Run with
// `node scripts/generate-tool-presets.mjs` after adding pair pages for new
// providers; tests/data/toolPresets.test.ts fails CI until presets exist.

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const SCHEMAS = path.join(ROOT, 'app', 'schemas', 'nodes');
const TARGET = path.join(ROOT, 'app', 'data', 'toolPresets.ts');

const READ = /^(list|get|fetch|search|read|query|check|find|download|count|describe|retrieve)_/;
const ACT = /^(create|send|submit|reply|update|add|append|write|upsert|post|edit|forward|assign|upload|insert)_/;
// Risky or boring for a DEFAULT act set: money movement, auth material, plumbing.
const ACT_SKIP = /webhook|token|secret|api_key|charge|refund|payout|transfer|payment|invoice|billing|meter|schema|index|permission|role|member|user_group/;
// Core nouns rank first — what an agent actually works with day to day.
const CORE = /message|issue|task|record|contact|deal|ticket|page|document|row|event|post|card|item|order|customer|product|incident|channel|thread|comment|file|quer(y|ies)|email|conversation|deploy|flag|note|lead|company|board|space|sheet|tweet|sms|call|user\b|collection|table/;

function opsOf(slug) {
    const schema = JSON.parse(
        fs.readFileSync(path.join(SCHEMAS, `${slug}.json`), 'utf8')
    );
    const reads = [];
    const acts = [];
    const all = [];
    for (const def of Object.values(schema.$defs ?? {})) {
        const op = def.properties?.operation ?? {};
        const name = op.const ?? op.enum?.[0];
        if (!name) continue;
        if (def['x-is-trigger'] || op['x-is-trigger'] || def['x-requires-tier'])
            continue;
        all.push(name);
        if (READ.test(name)) reads.push(name);
        else if (ACT.test(name) && !ACT_SKIP.test(name)) acts.push(name);
    }
    const rank = (a, b) =>
        (CORE.test(a) ? 0 : 1) - (CORE.test(b) ? 0 : 1) ||
        a.length - b.length ||
        a.localeCompare(b);
    reads.sort(rank);
    acts.sort(rank);
    all.sort(rank);
    return { reads, acts, all };
}

const DESTRUCTIVE = /^(delete|remove|drop|truncate|purge|permanently|ban|kick|revoke|uninstall|destroy)_/;

function presetsFor(slug) {
    const { reads, acts, all: allOps } = opsOf(slug);
    let everyday = [...reads.slice(0, 10), ...acts.slice(0, 8)];
    if (!everyday.length) {
        // Ops outside the verb taxonomy (translate_text, run_prompt, …):
        // everything safe, capped.
        everyday = allOps.filter((o) => !DESTRUCTIVE.test(o)).slice(0, 15);
    }
    const presets = [
        {
            id: 'everyday',
            name: 'Everyday use',
            description: 'Read data plus the common safe actions.',
            ops: [...everyday].sort(),
        },
    ];
    if (reads.length) {
        presets.push({
            id: 'read_only',
            name: 'Read-only',
            description: 'Look things up without changing anything.',
            ops: reads.slice(0, 10).sort(),
        });
    }
    return presets;
}

const source = fs.readFileSync(TARGET, 'utf8');

// Every op-tool provider gets presets (single-provider /agents pages exist for
// all of them, not just curated pairs), minus hand-curated CURATED entries.
const slugs = new Set();
for (const file of fs.readdirSync(SCHEMAS)) {
    if (!file.endsWith('.json')) continue;
    const schema = JSON.parse(fs.readFileSync(path.join(SCHEMAS, file), 'utf8'));
    if (schema['x-agent-tool-provider']) slugs.add(file.replace(/\.json$/, ''));
}
const curated = new Set(
    [...source.matchAll(/'(automation-[a-z0-9-]+)':\s*\[/g)]
        .map((m) => m[1])
        .filter((t) => source.indexOf(`'${t}':`) < source.indexOf('GENERATED_PRESETS_START'))
);

const generated = {};
for (const slug of [...slugs].sort()) {
    const type = `automation-${slug}`;
    if (curated.has(type)) continue;
    if (!fs.existsSync(path.join(SCHEMAS, `${slug}.json`))) {
        console.error(`!! no schema for ${slug} — skipped`);
        continue;
    }
    generated[type] = presetsFor(slug);
}

const block = `/* GENERATED_PRESETS_START — heuristic presets for the long-tail providers,
   derived from the generated schemas (reads + common safe act verbs, no
   destructive/plumbing ops). Regenerate via scripts/generate-tool-presets.mjs;
   the section between these markers is machine-written. */
const GENERATED: Record<string, ToolPreset[]> = ${JSON.stringify(generated, null, 4)};
/* GENERATED_PRESETS_END */`;

const next = source.replace(
    /\/\* GENERATED_PRESETS_START[\s\S]*GENERATED_PRESETS_END \*\//,
    block
);
if (next === source) {
    console.error('markers not found in toolPresets.ts');
    process.exit(1);
}
fs.writeFileSync(TARGET, next);
console.log(`wrote ${Object.keys(generated).length} generated preset sets`);
