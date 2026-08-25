// Verifies the two halves of the operation-search quality work against REAL
// generated schemas (not stubs): (1) the generic synonym engine, and (2) the
// per-operation `x-keywords` synonyms authored on integration nodes. buildFields
// mirrors exactly how OperationPicker.searchFieldsFor + NodeConfig.getOptionKeywords
// compose their weighted fields, so a passing test means the production picker
// ranks the same way.
import { describe, expect, it } from 'vitest';
import { getSchemaInfo } from '~/utils/schemaFieldExtractor';
import { getOptionDisplayName } from '~/utils/operationHelpers';
import { scoreFields, type SearchField } from '~/utils/fuzzySearch';
import { expandQueryTerm } from '~/utils/operationSynonyms';

function rankerFor(nodeType: string) {
    const info = getSchemaInfo(nodeType);
    if (!info?.hasDiscriminator)
        throw new Error(`${nodeType} should be a discriminated node`);
    const { options, discriminator, resolveRef } = info as any;
    const resolvedAt = (i: number) => {
        const o = options[i] as any;
        return o?.$ref ? (resolveRef(o.$ref) as any) : o;
    };
    const buildFields = (i: number): SearchField[] => {
        const label = getOptionDisplayName(info as any, i);
        const fields: SearchField[] = [
            { text: label.toLowerCase(), weight: 1, fuzzy: true },
        ];
        const r = resolvedAt(i);
        const opField = discriminator.fieldName
            ? r?.properties?.[discriminator.fieldName]
            : undefined;
        const rawKw = opField?.['x-keywords'] ?? r?.['x-keywords'];
        const kwStr = Array.isArray(rawKw) ? rawKw.join(' ') : rawKw;
        const kw = [
            discriminator.optionToValue.get(i)?.replace(/[_-]+/g, ' '),
            r?.title,
            kwStr,
        ]
            .filter(Boolean)
            .join(' ');
        if (kw)
            fields.push({ text: kw.toLowerCase(), weight: 0.6, fuzzy: true });
        const cat = opField?.['x-category'] ?? r?.['x-category'];
        if (cat) fields.push({ text: String(cat).toLowerCase(), weight: 0.4 });
        if (opField?.['x-is-trigger'])
            fields.push({ text: 'trigger', weight: 0.3 });
        if (r?.description)
            fields.push({
                text: String(r.description).toLowerCase(),
                weight: 0.25,
            });
        return fields;
    };
    const indices = options.map((_: unknown, i: number) => i);
    const valueAt = (i: number) => discriminator.optionToValue.get(i) as string;
    return (query: string) =>
        indices
            .map((i: number) => ({
                value: valueAt(i),
                score: scoreFields(buildFields(i), query),
            }))
            .filter((r: { score: number | null }) => r.score !== null)
            .sort(
                (a: { score: number | null }, b: { score: number | null }) =>
                    (b.score as number) - (a.score as number)
            );
}

describe('synonym engine', () => {
    it('expands verbs and entities symmetrically', () => {
        expect(expandQueryTerm('get')).toEqual(
            expect.arrayContaining(['read', 'fetch', 'list', 'retrieve'])
        );
        expect(expandQueryTerm('read')).toEqual(
            expect.arrayContaining(['get', 'fetch'])
        );
        expect(expandQueryTerm('rows')).toEqual(
            expect.arrayContaining(['row', 'record', 'records', 'entries'])
        );
        expect(expandQueryTerm('remove')).toEqual(
            expect.arrayContaining(['delete', 'drop'])
        );
    });

    it('leaves the literal term first and unknown terms unexpanded', () => {
        expect(expandQueryTerm('get')[0]).toBe('get');
        expect(expandQueryTerm('xyzzy')).toEqual(['xyzzy']);
    });

    it('does not bridge unrelated words (no AND-breaking false matches)', () => {
        // A synthetic "Send Message" action: "remove" must not match it via any
        // synonym, preserving the AND-semantics guarantee the picker relies on.
        const sendMessage: SearchField[] = [
            { text: 'send message', weight: 1, fuzzy: true },
            { text: 'send message', weight: 0.6, fuzzy: true },
        ];
        expect(scoreFields(sendMessage, 'remove')).toBeNull();
        expect(scoreFields(sendMessage, 'delete')).toBeNull();
    });
});

describe('google-sheets operation search (x-keywords + synonyms)', () => {
    const rank = rankerFor('automation-google-sheets');
    const top = (q: string) => rank(q)[0]?.value;

    it('"get rows" surfaces Read Sheet Data first (the reported bug)', () => {
        expect(top('get rows')).toBe('read_sheet_data');
    });

    it('intent phrasings all resolve to the read action', () => {
        expect(top('fetch rows')).toBe('read_sheet_data');
        expect(top('get values')).toBe('read_sheet_data');
        expect(top('list rows')).toBe('read_sheet_data');
        expect(top('read sheet')).toBe('read_sheet_data');
    });

    it('write / append / delete intents resolve to their actions', () => {
        expect(top('update cells')).toBe('write_sheet_data');
        expect(top('add row')).toBe('append_rows_to_sheet');
        expect(top('remove columns')).toBe('delete_sheet_columns');
        expect(top('new tab')).toBe('add_spreadsheet_sheet');
    });

    // A new operation whose LABEL overlaps a common intent outranks the right
    // action, because the label field outweighs x-keywords: "Update Cell
    // Borders" beat write_sheet_data on "update cells" even though that exact
    // phrase is one of its keywords. Adding operations must not shift these.
    it('formatting intents reach the formatting actions', () => {
        expect(top('bold header row')).toBe('format_cells');
        expect(top('freeze header row')).toBe('update_sheet_properties');
        expect(top('add borders')).toBe('format_borders');
        expect(top('alternating row colours')).toBe('add_alternating_colors');
        expect(top('autofit columns')).toBe('auto_resize_dimensions');
        expect(top('set column width')).toBe('set_dimension_size');
        expect(top('add filter')).toBe('set_basic_filter');
        expect(top('conditional formatting')).toBe('add_conditional_format_rule');
        expect(top('sort rows')).toBe('sort_range');
        expect(top('merge cells')).toBe('merge_cells');
    });

    it('formatting operations do not hijack data intents', () => {
        expect(top('clear range')).toBe('clear_sheet_range');
        expect(top('set values')).toBe('write_sheet_data');
        expect(top('rename tab')).toBe('rename_spreadsheet_sheet');
    });

    // "Create Table" beat add_spreadsheet_sheet on "new tab": labels outweigh
    // keywords, and "tab" fuzzy-matches "table". Hence "Convert Range To Table".
    it('table intents do not collide with sheet-tab intents', () => {
        expect(top('new tab')).toBe('add_spreadsheet_sheet');
        expect(top('add tab')).toBe('add_spreadsheet_sheet');
        expect(top('convert range to table')).toBe('add_table');
        expect(top('chip dropdown')).toBe('add_table');
        expect(top('delete table')).toBe('delete_table');
    });

    // Each family now has an add AND an edit operation, whose labels differ by
    // one verb. These pin that the two do not swallow each other.
    it('edit operations do not swallow their add counterparts', () => {
        expect(top('conditional formatting')).toBe('add_conditional_format_rule');
        expect(top('reorder colour rules')).toBe(
            'update_conditional_format_rule',
        );
        expect(top('alternating row colours')).toBe('add_alternating_colors');
        expect(top('change banding colours')).toBe('update_alternating_colors');
        expect(top('convert range to table')).toBe('add_table');
        expect(top('rename table')).toBe('update_table');
    });

    it('range protection and naming intents reach their actions', () => {
        expect(top('protect a range')).toBe('add_protected_range');
        expect(top('unprotect range')).toBe('delete_protected_range');
        expect(top('name a range')).toBe('add_named_range');
        expect(top('delete range name')).toBe('delete_named_range');
    });

    // "rename spreadsheet" is genuinely ambiguous — the file, or the tab? It
    // currently resolves to the tab (rename_spreadsheet_sheet), whose label
    // carries both words. Pin the unambiguous phrasings instead of distorting
    // the ranking to win a query that has two defensible answers.
    it('spreadsheet-level properties are reachable unambiguously', () => {
        expect(top('change spreadsheet title')).toBe(
            'update_spreadsheet_properties',
        );
        expect(top('set timezone')).toBe('update_spreadsheet_properties');
        expect(top('rename tab')).toBe('rename_spreadsheet_sheet');
    });

    // Third time a new operation's LABEL stole an existing intent, always via
    // a verb the synonym engine expands: "Insert Pivot Table" took "new tab"
    // (tab~table), "Set Cell Notes" took "set values". Both are noun-only now.
    it('data-wrangling intents reach their actions', () => {
        expect(top('pivot table')).toBe('insert_pivot_table');
        expect(top('add a note to a cell')).toBe('set_cell_notes');
        expect(top('remove duplicates')).toBe('remove_duplicate_rows');
        expect(top('split text to columns')).toBe('split_text_to_columns');
        expect(top('trim whitespace')).toBe('trim_whitespace');
        expect(top('move columns')).toBe('move_rows_or_columns');
        expect(top('paste values only')).toBe('copy_paste_range');
        expect(top('smart chip')).toBe('insert_smart_chips');
    });

    it('chart intents reach the chart actions', () => {
        expect(top('create a chart')).toBe('add_chart');
        expect(top('pie chart')).toBe('add_chart');
        expect(top('change chart type')).toBe('update_chart');
        expect(top('resize a chart')).toBe('move_chart');
        expect(top('delete a chart')).toBe('delete_chart');
    });

    it('view, grouping and slicer intents reach their actions', () => {
        expect(top('filter view')).toBe('save_filter_view');
        expect(top('saved filter')).toBe('save_filter_view');
        expect(top('group rows')).toBe('group_rows_or_columns');
        expect(top('collapse a group')).toBe('collapse_group');
        expect(top('add a slicer')).toBe('add_slicer');
    });

    it('metadata and data-source intents reach their actions', () => {
        expect(top('developer metadata')).toBe('create_developer_metadata');
        expect(top('connect a data source')).toBe('add_data_source');
        expect(top('refresh connected data')).toBe('refresh_data_source');
        expect(top('cancel a refresh')).toBe('cancel_data_source_refresh');
    });

    it('validation and teardown intents reach their actions', () => {
        expect(top('add a dropdown')).toBe('set_data_validation');
        expect(top('data validation')).toBe('set_data_validation');
        expect(top('remove dropdown')).toBe('clear_data_validation');
        expect(top('remove conditional formatting')).toBe(
            'delete_conditional_format_rules',
        );
        expect(top('remove banding')).toBe('clear_alternating_colors');
    });
});

describe('generic synonym recall', () => {
    it('returns results for a synonym query that shares no word with any label', () => {
        const rank = rankerFor('automation-gmail');
        // "fetch" appears in no Gmail label; via the synonym cluster it should
        // still reach get/read/list-style message actions.
        expect(rank('fetch').length).toBeGreaterThan(0);
    });
});

describe('authored x-keywords across integrations (intent → right action)', () => {
    // Each case: a phrase a user would realistically type, and the operation
    // value it must surface as the #1 result against the real generated schema.
    const cases: Array<[string, string, string]> = [
        ['automation-linear', 'file ticket', 'create_issue'],
        ['automation-linear', 'log bug', 'create_issue'],
        ['automation-gmail', 'compose email', 'send_email_message'],
        ['automation-gmail', 'check inbox', 'fetch_emails_from_inbox'],
        ['automation-airtable', 'new table', 'create_new_table'],
        ['automation-github-rest', 'merge pr', 'merge_pull_request'],
        ['automation-github-rest', 'squash merge', 'merge_pull_request'],
        ['automation-slack', 'post to channel', 'send_message_to_channel'],
        ['automation-slack', 'edit a message', 'update_existing_message'],
        ['automation-shopify', 'new gift card', 'create_gift_card'],
        ['automation-twitter', 'quote tweets', 'get_tweets_quoting_tweet'],
        ['automation-hubspot', 'new contact', 'create_contact'],
    ];
    it.each(cases)('%s: "%s" → %s ranks first', (nodeType, query, expected) => {
        const top = rankerFor(nodeType)(query)[0]?.value;
        expect(top).toBe(expected);
    });
});
