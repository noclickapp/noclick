// Live check that the OperationPicker's new fuzzy ranking produces good results
// against a REAL node schema (gmail), not hand-stubbed data. Mirrors exactly how
// OperationPicker.searchFieldsFor builds its weighted fields so we validate the
// production operation metadata + scorer together.
import { getOptionDisplayName } from '~/utils/operationHelpers';
import { getSchemaInfo as rawSchemaInfo } from '~/utils/schemaFieldExtractor';
import { getAgentToolOperations } from '~/utils/nodeSchemas';
import { scoreFields, type SearchField } from '~/utils/fuzzySearch';

export default async function () {
    const nodeType = 'automation-gmail';
    const info = rawSchemaInfo(nodeType);
    if (!info?.hasDiscriminator) throw new Error('gmail should be a discriminated node');
    const { options, discriminator, resolveRef } = info;

    const resolvedAt = (i: number) => {
        const o = options[i] as any;
        return o?.$ref ? (resolveRef(o.$ref) as any) : o;
    };

    const buildFields = (i: number): SearchField[] => {
        const label = getOptionDisplayName(info as any, i);
        const fields: SearchField[] = [{ text: label.toLowerCase(), weight: 1, fuzzy: true }];
        const value = discriminator.optionToValue.get(i);
        const r = resolvedAt(i);
        const opField = discriminator.fieldName ? r?.properties?.[discriminator.fieldName] : undefined;
        const rawKw = opField?.['x-keywords'] ?? r?.['x-keywords'];
        const kwStr = Array.isArray(rawKw) ? rawKw.join(' ') : rawKw;
        const kw = [value?.replace(/[_-]+/g, ' '), r?.title, kwStr].filter(Boolean).join(' ');
        if (kw) fields.push({ text: kw.toLowerCase(), weight: 0.6, fuzzy: true });
        const cat = discriminator.fieldName
            ? r?.properties?.[discriminator.fieldName]?.['x-category'] || r?.['x-category']
            : r?.['x-category'];
        if (cat) fields.push({ text: String(cat).toLowerCase(), weight: 0.4 });
        if (discriminator.fieldName && r?.properties?.[discriminator.fieldName]?.['x-is-trigger'])
            fields.push({ text: 'trigger', weight: 0.3 });
        if (r?.description) fields.push({ text: String(r.description).toLowerCase(), weight: 0.25 });
        return fields;
    };

    const allLabels: string[] = [];
    const indices = options.map((_: unknown, i: number) => i);
    for (const i of indices) allLabels.push(getOptionDisplayName(info as any, i));

    const rank = (query: string) =>
        indices
            .map((i) => ({ label: getOptionDisplayName(info as any, i), score: scoreFields(buildFields(i), query) }))
            .filter((r) => r.score !== null)
            .sort((a, b) => (b.score as number) - (a.score as number));

    // The literal-substring matcher the old picker used, for before/after contrast.
    const oldMatch = (query: string) =>
        allLabels.filter((l) => l.toLowerCase().includes(query.trim().toLowerCase()));

    const results: Record<string, unknown> = { totalOps: allLabels.length, labels: allLabels };

    // 1. Word-order independence: "email send" should still find a send action,
    //    where the old literal substring on the label returns nothing.
    const reordered = rank('email send');
    results.reordered_top3 = reordered.slice(0, 3).map((r) => r.label);
    const oldReorderedCount = oldMatch('email send').length;
    results.old_reordered_count = oldReorderedCount;

    // 2. Abbreviation: "msg" should surface message-related actions (old: only
    //    labels literally containing "msg", typically none).
    results.abbrev_top3 = rank('msg').slice(0, 3).map((r) => r.label);
    const oldAbbrevCount = oldMatch('msg').length;
    results.old_abbrev_count = oldAbbrevCount;

    // 3. A plain term still works and ranks sensibly.
    results.send_top3 = rank('send').slice(0, 3).map((r) => r.label);

    // 4. Agent-tool allowlist picker path: replicate AgentToolOperationsPicker's
    //    field-building against the real op-tool metadata and confirm the same
    //    fuzzy ranking applies (abbreviation finds the right tool).
    const toolOps = getAgentToolOperations(nodeType);
    const rankTools = (query: string) =>
        toolOps
            .map((op) => {
                const fields: SearchField[] = [
                    { text: op.displayName.toLowerCase(), weight: 1, fuzzy: true },
                    { text: op.operation.replace(/[_-]+/g, ' ').toLowerCase(), weight: 0.6, fuzzy: true },
                ];
                if (op.category) fields.push({ text: op.category.toLowerCase(), weight: 0.4 });
                if (op.description) fields.push({ text: op.description.toLowerCase(), weight: 0.25 });
                return { label: op.displayName, score: scoreFields(fields, query) };
            })
            .filter((r) => r.score !== null)
            .sort((a, b) => (b.score as number) - (a.score as number));
    results.toolOps_count = toolOps.length;
    results.tool_abbrev_top3 = rankTools('snd msg').slice(0, 3).map((r) => r.label);
    if (toolOps.length > 0 && rankTools('snd msg').length === 0) {
        throw new Error('agent-tool fuzzy ranking found nothing for "snd msg"');
    }

    // Assertions: the new search must beat the literal one on at least one of the
    // hard cases, and never crash producing rankings.
    if (reordered.length === 0 && rank('msg').length === 0) {
        throw new Error('fuzzy search returned nothing for both reordered and abbreviation queries');
    }
    if (reordered.length <= oldReorderedCount && rank('msg').length <= oldAbbrevCount) {
        throw new Error('fuzzy search did not improve recall over literal substring on any hard case');
    }

    return results;
}
