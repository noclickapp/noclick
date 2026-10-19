// How a file looks in a list: a thumbnail when there is one to show, else its
// type's glyph; and the type itself, read from the name.
import { Archive, Code2, File, FileText, Film, Image as ImageIcon, Music, Table2 } from 'lucide-react';
import type { FileEntry, FileKind } from '~/components/dashboard/types';
import { workspaceFileUrl } from '~/hooks/useAgentWorkspaceFiles';
import { cn } from '~/lib/utils';

const GLYPHS: Record<FileKind, typeof File> = {
    image: ImageIcon,
    video: Film,
    audio: Music,
    doc: FileText,
    data: Table2,
    code: Code2,
    archive: Archive,
    other: File,
};

export function FileGlyph({ kind, className }: { kind: FileKind; className?: string }) {
    const Glyph = GLYPHS[kind];
    return <Glyph className={cn('h-4 w-4 shrink-0 text-foreground/65 dark:text-foreground/50', className)} strokeWidth={1.75} />;
}

/** A real thumbnail for images and videos that already have a URL; the glyph otherwise. */
export function FileThumb({ file, size = 32 }: { file: FileEntry; size?: number }) {
    const src = file.kind === 'image' || file.kind === 'video' ? (file.url ?? (file.urlPath ? workspaceFileUrl(file.urlPath) : null)) : null;
    const box = { width: size, height: size };
    if (src) {
        return (
            <span className="shrink-0 overflow-hidden rounded-lg bg-foreground/[0.05] ring-1 ring-inset ring-foreground/[0.06]" style={box}>
                {file.kind === 'video' ? (
                    // The first frame is the thumbnail; metadata-only, so no download.
                    <video src={src} muted playsInline preload="metadata" className="h-full w-full object-cover" />
                ) : (
                    <img src={src} alt="" loading="lazy" className="h-full w-full object-cover" />
                )}
            </span>
        );
    }
    return (
        <span className="grid shrink-0 place-items-center rounded-lg bg-foreground/[0.05]" style={box}>
            <FileGlyph kind={file.kind} />
        </span>
    );
}

export function fileKindFromPath(path: string): FileKind {
    const ext = path.includes('.') ? path.slice(path.lastIndexOf('.') + 1).toLowerCase() : '';
    if (['png', 'jpg', 'jpeg', 'gif', 'webp', 'svg'].includes(ext)) return 'image';
    if (['mp4', 'webm', 'mov', 'm4v', 'mkv'].includes(ext)) return 'video';
    if (['mp3', 'wav', 'ogg', 'oga', 'm4a', 'aac'].includes(ext)) return 'audio';
    if (['csv', 'tsv', 'xlsx', 'json', 'parquet'].includes(ext)) return 'data';
    if (['py', 'js', 'jsx', 'mjs', 'ts', 'tsx', 'css', 'html', 'sh', 'sql', 'yaml', 'yml', 'toml'].includes(ext)) return 'code';
    if (['zip', 'tar', 'gz', '7z'].includes(ext)) return 'archive';
    if (['md', 'mdx', 'txt', 'pdf', 'doc', 'docx', 'log'].includes(ext)) return 'doc';
    return 'other';
}

export function basename(path: string): string {
    const i = path.lastIndexOf('/');
    return i >= 0 ? path.slice(i + 1) : path;
}

/** A folder of a flat listing: its path (ending in /), and what's under it at any depth. */
export interface FolderEntry {
    name: string;
    path: string;
    files: number;
    size: number;
    mtime: string;
}

/** What folder `dir` ('' the top, else ending in /) holds of a flat listing: its folders by name, then its own files as listed. */
export function folderListing(files: readonly FileEntry[], dir: string): { folders: FolderEntry[]; files: FileEntry[] } {
    const folders = new Map<string, FolderEntry>();
    const own: FileEntry[] = [];
    for (const file of files) {
        if (!file.path.startsWith(dir)) continue;
        const rest = file.path.slice(dir.length);
        const slash = rest.indexOf('/');
        if (slash < 0) {
            own.push(file);
            continue;
        }
        const name = rest.slice(0, slash);
        const folder = folders.get(name) ?? { name, path: `${dir}${name}/`, files: 0, size: 0, mtime: '' };
        folder.files += 1;
        folder.size += file.size;
        if (file.mtime > folder.mtime) folder.mtime = file.mtime;
        folders.set(name, folder);
    }
    return { folders: [...folders.values()].sort((a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: 'base' })), files: own };
}
