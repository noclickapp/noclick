// The repos API's answers as production gave them on 2026-10-09, read from a throwaway repo
// (the API's own views): the builders below make every fake repo answer in those shapes, wherever a
// page that shows a repo is tested, so a fake doesn't drift from what the pages really get.
//
// What the recording showed that a page must not assume otherwise: a commit made through the API says
// how many files it changed, a listed one doesn't (files_changed null); a listed commit's branch is the
// branch asked for, not where the commit was made; a repo's last_commit carries no branch or count; a
// directory's paths run from the repo's root, directories first, and a directory has no size or sha;
// size_bytes stays 0 until the hourly sweep measures the repo; a named ref that doesn't resolve is a 404.

type Json = Record<string, unknown>;

export interface CommitRecord {
    sha: string;
    message: string;
    author: string;
    created_at: string;
}

/** `repo_view`: a repo as GET /v1/repos(/{id}) gives it. */
export function repoWire(fields: {
    id: string;
    name: string;
    created_at: string;
    default_branch?: string;
    size_bytes?: number;
    last_commit?: CommitRecord | null;
    used_by?: { id: string; name: string }[];
    user_id?: string | null;
}): Json {
    return {
        object: 'repo',
        id: fields.id,
        name: fields.name,
        default_branch: fields.default_branch ?? 'main',
        size_bytes: fields.size_bytes ?? 0,
        last_commit: fields.last_commit ? lastCommitWire(fields.last_commit) : null,
        used_by: (fields.used_by ?? []).map((u) => ({ kind: 'project', id: u.id, name: u.name })),
        user_id: fields.user_id ?? null,
        created_at: fields.created_at,
    };
}

/** `_commit_record`: the default branch's newest commit, on the repo. */
export function lastCommitWire(c: CommitRecord): Json {
    return { sha: c.sha, author: c.author, message: c.message, created_at: c.created_at };
}

/** `commit_view`: POST .../commits answers with `files_changed`; a history page lists it null, under the branch asked for. */
export function commitWire(c: CommitRecord, branch: string, filesChanged: number | null = null): Json {
    return { object: 'commit', sha: c.sha, message: c.message, author: c.author, branch, created_at: c.created_at, files_changed: filesChanged };
}

export function branchWire(name: string, head: string, updatedAt: string): Json {
    return { object: 'branch', name, head, updated_at: updatedAt };
}

/** A directory's entry: a file with its size and git blob id, a directory with neither. */
export function fileWire(path: string, file: { size: number; sha: string } | null): Json {
    return { object: 'repo_file', path, type: file ? 'file' : 'dir', size: file?.size ?? null, sha: file?.sha ?? null };
}

export function listWire(data: readonly unknown[], nextCursor: string | null = null): Json {
    return { object: 'list', data, next_cursor: nextCursor };
}

/** POST .../clone_url: a URL whose user is `t` and whose password is the token, on Code Storage's git host. */
export function cloneUrlWire(repoId: string, token: string, write: boolean, expiresAt: string): Json {
    return { object: 'clone_url', url: `https://t:${token}@noclick.code.storage/${repoId}.git`, write, expires_at: expiresAt };
}

export function deletedWire(repoId: string): Json {
    return { object: 'repo', id: repoId, deleted: true };
}

/**
 * The errors the pages show, each as its error envelope (`error.type`, `message`, `next_step`, details).
 * `noRef` is what service.py answers once the store's 404 for a ref is read as one; before that, production
 * answered a ref that doesn't resolve with a 502 that the edge turned into an HTML page.
 */
export const REPO_ERRORS = {
    noRef: (ref: string) => ({
        status: 404,
        error: { type: 'not_found', message: `The repo has no branch, tag or commit '${ref}'.`, next_step: 'List its branches with GET .../branches.', field: 'ref', ref },
    }),
    noFile: (path: string, branch: string) => ({
        status: 404,
        error: { type: 'not_found', message: `No file at '${path}' in ${branch}.`, next_step: "List the repo's files with GET .../files?prefix=.", field: 'path', path },
    }),
    noRepo: () => ({ status: 404, error: { type: 'not_found', message: 'No such repo.', next_step: 'List repos with GET /v1/repos.' } }),
    deployed: (apps: { id: string; name: string }[]) => ({
        status: 409,
        error: {
            type: 'conflict',
            message: `The repo is deployed by ${apps.map((a) => a.name).join(', ')}.`,
            next_step: 'Delete those apps first, or point them at another repo.',
            used_by: apps.map((a) => ({ kind: 'project', id: a.id, name: a.name })),
        },
    }),
    taken: (name: string, existingId: string) => ({
        status: 409,
        error: { type: 'conflict', message: `A repo named '${name}' already exists.`, next_step: 'Use that one (Repo.from_name), or pick another name.', existing_id: existingId },
    }),
};

// ── the recording ─────────────────────────────────────────────────────────────
// Verbatim but for the clone URL's token and the repo's created_at (a timestamp to the microsecond, as
// Postgres keeps it). The repo and its app were deleted after.

export const RECORDED_REPO_ID = 'b605410a-f391-4ef7-ad33-4d7efab43c23';
const MAIN_HEAD = 'c61eeaec93fe5895b8347745c561f3cdf46a2923';
const FIRST = '2ce72c6adab0e7bb71f2b16961ffe94c387cfab0';

export const RECORDED = {
    created: {
        object: 'repo',
        id: RECORDED_REPO_ID,
        name: 'zz-audit-0e7fbd',
        default_branch: 'main',
        size_bytes: 0,
        last_commit: null,
        used_by: [],
        user_id: null,
        created_at: '2026-10-09T18:23:51.814251+00:00',
    },
    emptyFiles: { object: 'list', next_cursor: null, data: [] },
    emptyCommits: { object: 'list', data: [], next_cursor: null },
    committed: {
        object: 'commit',
        sha: FIRST,
        message: 'Start the audit',
        author: 'NoClick <noreply@noclick.com>',
        branch: 'main',
        created_at: '2026-10-09T18:23:52+00:00',
        files_changed: 7,
    },
    repo: {
        object: 'repo',
        id: RECORDED_REPO_ID,
        name: 'zz-audit-0e7fbd',
        default_branch: 'main',
        size_bytes: 300437,
        last_commit: { sha: MAIN_HEAD, author: 'NoClick <noreply@noclick.com>', message: 'Tidy', created_at: '2026-10-09T18:23:53+00:00' },
        used_by: [{ kind: 'project', id: 'cced10d4-3c81-40b1-a6a3-9330abdcdc68', name: 'zz-audit-0e7fbd' }],
        user_id: null,
        created_at: '2026-10-09T18:23:51.814251+00:00',
    },
    branches: {
        object: 'list',
        data: [
            { object: 'branch', name: 'main', head: MAIN_HEAD, updated_at: '2026-10-09T18:23:53+00:00' },
            { object: 'branch', name: 'feature/audit', head: '96d6a1b805099e479380764125a5da470d3a06d2', updated_at: '2026-10-09T18:23:53+00:00' },
        ],
        next_cursor: null,
    },
    historyPage: {
        object: 'list',
        data: [{ object: 'commit', sha: MAIN_HEAD, message: 'Tidy', author: 'NoClick <noreply@noclick.com>', branch: 'main', created_at: '2026-10-09T18:23:53+00:00', files_changed: null }],
        next_cursor: '1',
    },
    featureHistory: {
        object: 'list',
        data: [
            { object: 'commit', sha: '96d6a1b805099e479380764125a5da470d3a06d2', message: 'Feature work', author: 'Ana Audit <ana@noclick.test>', branch: 'feature/audit', created_at: '2026-10-09T18:23:53+00:00', files_changed: null },
            { object: 'commit', sha: FIRST, message: 'Start the audit', author: 'NoClick <noreply@noclick.com>', branch: 'feature/audit', created_at: '2026-10-09T18:23:52+00:00', files_changed: null },
        ],
        next_cursor: null,
    },
    root: {
        object: 'list',
        next_cursor: null,
        data: [
            { object: 'repo_file', path: 'assets', type: 'dir', size: null, sha: null },
            { object: 'repo_file', path: 'docs', type: 'dir', size: null, sha: null },
            { object: 'repo_file', path: 'src', type: 'dir', size: null, sha: null },
            { object: 'repo_file', path: 'README.md', type: 'file', size: 17, sha: '25d1f5a423a17e24eb60aa67f445710aa5f79798' },
            { object: 'repo_file', path: 'big.txt', type: 'file', size: 300001, sha: 'f07ce08792006531fee7a5b97808658dcc7249a9' },
            { object: 'repo_file', path: 'index.html', type: 'file', size: 56, sha: 'a48d20752cfa99ae1b8d8897c83cb28c9ade2410' },
        ],
    },
    src: { object: 'list', next_cursor: null, data: [{ object: 'repo_file', path: 'src/app.ts', type: 'file', size: 22, sha: '20568bbd1d6869e49717fa100b603c9ad1f14c4d' }] },
    docs: { object: 'list', next_cursor: null, data: [{ object: 'repo_file', path: 'docs/naïve café.md', type: 'file', size: 14, sha: '139e3bac7bfa63fa23a34d9b21821ee26bfef0f1' }] },
    readme: '# Audit\n\nEdited.\n',
    cloneUrl: { object: 'clone_url', url: `https://t:<token>@noclick.code.storage/${RECORDED_REPO_ID}.git`, write: false, expires_at: '2026-10-09T19:26:01+00:00' },
    deleted: { object: 'repo', id: RECORDED_REPO_ID, deleted: true },
    missingFile: {
        error: { type: 'not_found', message: "No file at 'missing.txt' in main.", next_step: "List the repo's files with GET .../files?prefix=.", field: 'path', path: 'missing.txt' },
    },
    deployedConflict: {
        error: {
            type: 'conflict',
            message: 'The repo is deployed by zz-audit-0e7fbd.',
            next_step: 'Delete those apps first, or point them at another repo.',
            used_by: [{ kind: 'project', id: 'cced10d4-3c81-40b1-a6a3-9330abdcdc68', name: 'zz-audit-0e7fbd' }],
        },
    },
} as const;
