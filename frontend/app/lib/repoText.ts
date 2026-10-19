// Reading a repo's files in a page: names that are never text aren't fetched,
// nor are files too big to show, and bytes that aren't UTF-8 (or hold NULs)
// read as null, so a binary file is named and never dumped. The developer
// console's repo drawer and Resources' repo page share it.

const BINARY_EXTENSIONS = /\.(png|jpe?g|gif|webp|ico|pdf|zip|gz|woff2?|ttf|otf|mp[34]|wav|wasm)$/i;

/** The most a page reads and shows of one file; a bigger one is named with its size. */
export const MAX_SHOWN_BYTES = 512 * 1024;

export function isBinaryPath(path: string): boolean {
    return BINARY_EXTENSIONS.test(path);
}

/** Text, or null for bytes that aren't UTF-8 (or hold NULs). */
export function decodeText(bytes: Uint8Array): string | null {
    try {
        const text = new TextDecoder('utf-8', { fatal: true }).decode(bytes);
        return text.includes('\u0000') ? null : text;
    } catch {
        return null;
    }
}

/** A commit's author as the API gives it, `Dana Reyes <dev@acme.test>`, by name: `Dana Reyes`. */
export function authorName(author: string): string {
    return author.replace(/\s*<[^>]*>\s*$/, '');
}

/**
 * The `ref` a read names for `branch`: none for the repo's default branch, which the API reads as its head.
 * Named, a default branch with no commit yet is not found, where unnamed an empty repo reads as empty.
 */
export function refFor(branch: string, defaultBranch: string): string | undefined {
    return branch === defaultBranch ? undefined : branch;
}

/** The folder a path sits in, as a listing names it: '' for the root, else ending in '/'. */
export function parentDir(path: string): string {
    return path.slice(0, path.lastIndexOf('/') + 1);
}
