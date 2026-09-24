// Share the read-style action shortcut between workflow tools and credential rules.
// This name-based grouping is a selection aid, not an API side-effect guarantee.
const READ_PREFIXES = new Set([
    'list',
    'get',
    'search',
    'fetch',
    'read',
    'query',
    'count',
    'check',
]);

export const isReadOperation = (operation: string) =>
    READ_PREFIXES.has(operation.split('_')[0]);
