// Curated synonym clusters for operation/action search, shared by the fuzzy
// scorer (fuzzySearch.ts). Operation labels use one verb/noun ("Read Sheet
// Data", "List Records") but users search with another ("get rows", "fetch
// entries"). Expanding each query token through these clusters at search time
// lifts recall across every node's operations without hand-authoring synonyms
// on each one — the per-operation `x-keywords` schema field then covers the
// residual label-vs-intent gaps the generic clusters can't bridge.
//
// Each inner array is a set of mutually-interchangeable words AS THEY APPEAR in
// operation labels/values. Membership is symmetric (any word in a cluster
// expands to all the others). A word may appear in several clusters; the index
// unions them. Keep entries to single lowercase tokens — the query is tokenized
// on whitespace before expansion, so multi-word phrases never match here.

export const SYNONYM_CLUSTERS: string[][] = [
    // ---- verbs ----
    [
        'get',
        'read',
        'fetch',
        'retrieve',
        'pull',
        'load',
        'show',
        'view',
        'display',
        'list',
    ],
    ['search', 'find', 'query', 'lookup', 'locate', 'filter'],
    ['create', 'add', 'new', 'make', 'insert', 'register', 'generate', 'build'],
    ['update', 'edit', 'modify', 'change', 'patch', 'set'],
    ['delete', 'remove', 'drop', 'erase', 'destroy', 'clear', 'trash'],
    ['send', 'dispatch', 'deliver', 'submit', 'transmit'],
    // "share" is deliberately NOT here — it's a distinct action in many nodes
    // (share a file, share to a channel) and conflated with post/publish it
    // outranks the literal action a user means (e.g. "post to channel").
    ['post', 'publish', 'tweet', 'broadcast'],
    ['upload', 'import', 'attach'],
    ['download', 'export'],
    ['duplicate', 'copy', 'clone'],
    ['move', 'transfer', 'relocate'],
    ['merge', 'combine', 'join'],
    ['cancel', 'abort', 'void', 'revoke'],
    ['approve', 'accept', 'confirm'],
    ['enable', 'activate'],
    ['disable', 'deactivate'],
    ['start', 'begin', 'launch', 'run', 'execute'],
    ['stop', 'end', 'finish', 'complete', 'close'],
    ['subscribe', 'watch', 'follow', 'monitor'],
    ['unsubscribe', 'unwatch', 'unfollow'],
    ['reply', 'respond', 'answer', 'comment'],
    ['like', 'favorite', 'react', 'star', 'upvote'],
    ['count', 'total', 'sum', 'aggregate'],
    // ---- entities ----
    [
        'row',
        'rows',
        'record',
        'records',
        'entry',
        'entries',
        'item',
        'items',
        'line',
        'lines',
    ],
    ['message', 'messages', 'msg', 'msgs', 'dm', 'dms', 'text', 'chat'],
    [
        'file',
        'files',
        'document',
        'documents',
        'doc',
        'docs',
        'attachment',
        'attachments',
    ],
    ['folder', 'folders', 'directory', 'directories', 'dir'],
    [
        'user',
        'users',
        'member',
        'members',
        'person',
        'people',
        'contact',
        'contacts',
        'account',
        'accounts',
    ],
    ['channel', 'channels', 'room', 'rooms', 'conversation', 'conversations'],
    ['comment', 'comments', 'reply', 'replies', 'note', 'notes'],
    ['label', 'labels', 'tag', 'tags', 'category', 'categories'],
    ['event', 'events', 'meeting', 'meetings', 'appointment', 'appointments'],
    ['task', 'tasks', 'todo', 'todos', 'issue', 'issues', 'ticket', 'tickets'],
    ['email', 'emails', 'mail', 'mails'],
    ['sheet', 'sheets', 'tab', 'tabs', 'worksheet', 'worksheets'],
    ['spreadsheet', 'spreadsheets', 'workbook', 'workbooks'],
    ['column', 'columns', 'col', 'cols', 'field', 'fields'],
    ['value', 'values', 'data', 'cell', 'cells'],
    ['post', 'posts', 'tweet', 'tweets', 'status', 'toot'],
    ['page', 'pages'],
    ['order', 'orders', 'purchase', 'purchases'],
    ['product', 'products', 'item', 'items'],
    ['customer', 'customers', 'client', 'clients'],
    ['invoice', 'invoices', 'bill', 'bills'],
    ['payment', 'payments', 'charge', 'charges', 'transaction', 'transactions'],
    ['subscriber', 'subscribers', 'audience', 'audiences'],
    ['campaign', 'campaigns'],
    ['video', 'videos', 'clip', 'clips'],
    ['image', 'images', 'photo', 'photos', 'picture', 'pictures'],
    ['board', 'boards'],
    ['project', 'projects'],
    ['group', 'groups', 'team', 'teams'],
    ['webhook', 'webhooks', 'hook', 'hooks'],
];

/** token → other words that share at least one cluster with it. */
const SYNONYM_INDEX: Map<string, string[]> = (() => {
    const sets = new Map<string, Set<string>>();
    for (const cluster of SYNONYM_CLUSTERS) {
        for (const word of cluster) {
            let set = sets.get(word);
            if (!set) {
                set = new Set();
                sets.set(word, set);
            }
            for (const other of cluster) if (other !== word) set.add(other);
        }
    }
    const out = new Map<string, string[]>();
    for (const [word, set] of sets) out.set(word, Array.from(set));
    return out;
})();

/** The query token followed by its synonyms (the literal always comes first so
 *  callers can score it without the synonym penalty). */
export function expandQueryTerm(term: string): string[] {
    const synonyms = SYNONYM_INDEX.get(term);
    return synonyms ? [term, ...synonyms] : [term];
}
