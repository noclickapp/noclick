// Per-credential audits must notice removed credentials as well as changed wording.
// Checking the file inventory prevents an obsolete review from silently surviving.
import { existsSync, readdirSync } from 'node:fs';
import { join, relative } from 'node:path';
import { expect } from 'vitest';

export async function expectCredentialSnapshots(kind: 'labels' | 'copy', snapshots: Map<string, string>): Promise<void> {
    for (const [path, content] of snapshots) await expect(content).toMatchFileSnapshot(path);
    const root = join(__dirname, '__snapshots__/credentials');
    const files: string[] = [];
    function walk(dir: string): void {
        if (!existsSync(dir)) return;
        for (const entry of readdirSync(dir, { withFileTypes: true })) {
            const path = join(dir, entry.name);
            if (entry.isDirectory()) walk(path);
            else if (entry.name.endsWith(`.${kind}.snap.txt`)) files.push(`./${relative(__dirname, path)}`);
        }
    }
    walk(root);
    expect(files.sort(), `Every ${kind} review must still name a credential`).toEqual([...snapshots.keys()].sort());
}
