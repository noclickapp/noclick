// A file's kind, read from the extension its name ends in: Resources draws a file by it, a preview opens it by it, and
// a Markdown embed (`![caption](url)`) of it plays, shows or becomes a file card by it. A file NoClick made is linked
// by a URL ending in its filename, so its URL names its kind, as its stored type does for the phone channels.
import type { FileKind } from '~/components/dashboard/types';

const KINDS: Record<Exclude<FileKind, 'other'>, readonly string[]> = {
    image: ['png', 'jpg', 'jpeg', 'gif', 'webp', 'svg', 'avif', 'bmp', 'ico'],
    video: ['mp4', 'mov', 'webm', 'm4v', 'mkv'],
    audio: ['mp3', 'm4a', 'aac', 'ogg', 'oga', 'opus', 'wav', 'amr'],
    data: ['csv', 'tsv', 'xls', 'xlsx', 'ods', 'numbers', 'json', 'jsonl', 'ndjson', 'parquet'],
    code: ['py', 'js', 'jsx', 'mjs', 'cjs', 'ts', 'tsx', 'css', 'html', 'htm', 'xml', 'sh', 'sql', 'yaml', 'yml', 'toml', 'ini', 'rb', 'go', 'rs', 'java'],
    archive: ['zip', 'tar', 'gz', 'tgz', '7z', 'rar'],
    doc: ['pdf', 'doc', 'docx', 'odt', 'rtf', 'pages', 'ppt', 'pptx', 'odp', 'key', 'txt', 'md', 'mdx', 'log', 'epub'],
};
const KIND_OF = new Map<string, FileKind>(Object.entries(KINDS).flatMap(([kind, exts]) => exts.map((ext) => [ext, kind as FileKind])));

/** Files a preview shows as text (the rest of a preview is the browser's own: images, video, audio, PDF). */
const TEXT = new Set([
    'txt', 'md', 'mdx', 'csv', 'tsv', 'json', 'jsonl', 'ndjson', 'xml', 'yaml', 'yml', 'toml', 'ini', 'log',
    'html', 'htm', 'css', 'js', 'jsx', 'mjs', 'cjs', 'ts', 'tsx', 'py', 'rb', 'go', 'rs', 'java', 'sh', 'sql',
]);
/** The most text a preview reads, as an agent workspace's preview does. */
const TEXT_PREVIEW_BYTES = 512 * 1024;

/** The extension a name (or path) ends in, lower case; '' for none. Digits alone ("10.30.45") are not one. */
export function extensionOf(name: string): string {
    return /\.([a-z0-9]*[a-z][a-z0-9]*)$/i.exec(name)?.[1].toLowerCase() ?? '';
}

export function fileKindOf(name: string): FileKind {
    return KIND_OF.get(extensionOf(name)) ?? 'other';
}

/**
 * The type a preview renders a file as, read from its name (a listing carries no content type, and one guessed when it
 * was stored can be wrong: a .ts file is stored as video), or null where it has no preview. Text is read only at a
 * known size the preview can hold.
 */
export function previewType(name: string, size: number | null): string | null {
    const ext = extensionOf(name);
    if (ext === 'pdf') return 'application/pdf';
    const kind = fileKindOf(name);
    if (kind === 'image' || kind === 'video' || kind === 'audio') return `${kind}/${ext}`;
    if (!TEXT.has(ext) || size === null || size > TEXT_PREVIEW_BYTES) return null;
    return ext === 'md' || ext === 'mdx' ? 'text/markdown' : ext === 'csv' ? 'text/csv' : 'text/plain';
}

/** The file a URL names: its last path segment, decoded. */
export function fileNameOf(url: string): string {
    const last = url.split(/[?#]/)[0].split('/').pop() ?? '';
    try {
        return decodeURIComponent(last);
    } catch {
        return last;
    }
}

export type EmbedKind = 'image' | 'audio' | 'video' | 'file';

/** How a Markdown embed shows: a picture, a player, or any other named file as a card. A URL naming no extension is
 *  a picture, as image hosts often leave it off. */
export function embedKindOf(url: string): EmbedKind {
    const name = fileNameOf(url);
    const kind = fileKindOf(name);
    if (kind === 'image' || kind === 'audio' || kind === 'video') return kind;
    return extensionOf(name) ? 'file' : 'image';
}
