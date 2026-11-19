// The machine page's one filesystem: a conversation's sandbox files as folders under its workspace, each file the agent
// changed in the conversation marked (added or changed) with its newest diff, read from the edits its turns kept.
import type { Message, VolumeEntry } from 'noclick';

export interface Changed {
    how: 'added' | 'changed' | 'deleted';
    /** Its newest diff, as the turn kept it. */
    patch: string;
    at: Date | null;
}

export interface FileNode {
    path: string;
    size: number | null;
    changed: Changed | null;
    /** A file whose values are secrets: its names show, never a value. */
    secret: boolean;
}

export interface Dir {
    path: string;
    name: string;
    dirs: Dir[];
    files: FileNode[];
}

const SECRET_FILE = /(^|\/)\.env(\.[\w-]+)?$/;
export const isSecretFile = (path: string) => SECRET_FILE.test(path);
export const nameOf = (path: string) => path.slice(path.lastIndexOf('/') + 1);

/** Each file the conversation's turns edited, by path, with its newest diff. */
export function changedFiles(messages: readonly Message[]): Map<string, Changed> {
    const out = new Map<string, Changed>();
    for (const m of messages)
        for (const step of m.steps ?? [])
            for (const d of step.diffs) {
                if (!d.path) continue;
                const prior = out.get(d.path);
                const how = d.change === 'add' ? 'added' : d.change === 'delete' ? 'deleted' : prior?.how === 'added' ? 'added' : 'changed';
                out.set(d.path, { how, patch: d.diff, at: step.createdAt });
            }
    return out;
}

/** The files as one tree under its root, in name order, folders first; a changed file the listing lacks (deleted, or
 *  outside it) is left out. */
export function buildTree(root: string, entries: readonly VolumeEntry[], changed: ReadonlyMap<string, Changed>): Dir {
    const top: Dir = { path: root, name: root, dirs: [], files: [] };
    const dirOf = (path: string): Dir => {
        const rel = path.slice(root.length).replace(/^\/+/, '');
        let dir = top;
        for (const part of rel ? rel.split('/') : []) {
            const at = `${dir.path.replace(/\/$/, '')}/${part}`;
            let next = dir.dirs.find((d) => d.path === at);
            if (!next) {
                next = { path: at, name: part, dirs: [], files: [] };
                dir.dirs.push(next);
            }
            dir = next;
        }
        return dir;
    };
    for (const e of entries) {
        if (!e.path.startsWith(root)) continue;
        if (e.type === 'directory') dirOf(e.path);
        else dirOf(e.path.slice(0, e.path.lastIndexOf('/'))).files.push({ path: e.path, size: e.size, changed: changed.get(e.path) ?? null, secret: isSecretFile(e.path) });
    }
    const sort = (d: Dir) => {
        d.dirs.sort((a, b) => a.name.localeCompare(b.name));
        d.files.sort((a, b) => nameOf(a.path).localeCompare(nameOf(b.path)));
        d.dirs.forEach(sort);
    };
    sort(top);
    return top;
}

export const changedIn = (dir: Dir): number => dir.files.filter((f) => f.changed).length + dir.dirs.reduce((n, d) => n + changedIn(d), 0);

/** Every file in the tree, in the order it lists them. */
export function filesOf(dir: Dir): FileNode[] {
    return [...dir.dirs.flatMap(filesOf), ...dir.files];
}

/** "1.2 KB", "38 MB". */
export function sizeText(bytes: number | null): string {
    if (bytes === null) return '';
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

/** A secret file's names, never its values. */
export function secretNames(text: string): string[] {
    return text
        .split('\n')
        .map((l) => l.trim())
        .filter((l) => l && !l.startsWith('#'))
        .map((l) => l.replace(/^export\s+/, '').split('=')[0].trim())
        .filter(Boolean);
}
