// Exercise personal attachments through the real dashboard file components.
// Isolated actions keep the signed-in account untouched while checking preview,
// download and deletion of multiple uploads with the same filename.
import { useState } from 'react';
import { createRoot } from 'react-dom/client';
import { flushSync } from 'react-dom';
import { FilesCompact, FilesFull } from '~/components/dashboard/sections';
import { FilePreviewDialog, type FilePreviewRequest } from '~/components/dashboard/FilePreviewDialog';
import { DashboardActionsContext, useDashboardActions } from '~/components/dashboard/primitives';
import type { DashboardData, FileSource } from '~/components/dashboard/types';
import { nc } from '~/lib/nc';

export default async function () {
    const imageUrl = (color: string) => `data:image/svg+xml,${encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="40" height="40"><rect width="40" height="40" fill="${color}"/></svg>`)}`;
    const now = '2026-09-25T10:00:00Z';
    const files: FileSource[] = [{
        id: 'resources:account', kind: 'resources', label: 'Personal files',
        sublabel: 'Uploads & attachments', writable: true,
        files: ['first', 'second'].map((id, i) => ({
            resourceId: id, path: 'image.jpg', kind: 'image', resourceType: 'image',
            mime: 'image/svg+xml', url: imageUrl(i ? 'blue' : 'red'), size: 100, mtime: now,
        })),
    }, {
        id: 'resources:workflow', kind: 'resources', label: 'Workflow files', sublabel: 'Uploads & outputs',
        workflow: { id: 'workflow', name: 'Workflow files', marks: [] }, writable: true,
        files: [{ resourceId: 'workflow-file', path: 'image.jpg', kind: 'image', size: 100, mtime: now }],
    }];
    const base: DashboardData = {
        workspace: { name: 'Review', kind: 'personal', userName: 'Sam' }, now,
        attention: [], runs: { days: [], byWorkflow: [], recent: [] },
        agents: { running: [], turns: [] }, files, credentials: [], triggers: [], upcoming: [], notifications: [],
        credits: { used: 0, cap: 100, period: 'month', nextRefreshAt: '', topup: 0, tier: 'free', spendByDay: [], topSpenders: [] },
    };
    const deleted: string[] = [];
    const uploads: string[] = [];
    function Harness() {
        const defaults = useDashboardActions();
        const [sources, setSources] = useState(files);
        const [preview, setPreview] = useState<FilePreviewRequest | null>(null);
        const data = { ...base, files: sources };
        return <DashboardActionsContext.Provider value={{
            ...defaults,
            openFile: (file, source) => setPreview({ file, source }),
            uploadTo: (source) => uploads.push(source.id),
            deleteFile: async (file, source) => {
                deleted.push(file.resourceId!);
                setSources((current) => current.map((s) => s.id === source.id
                    ? { ...s, files: s.files.filter((f) => f.resourceId !== file.resourceId) } : s));
            },
        }}>
            <div data-view="compact"><FilesCompact data={data} /></div>
            <div data-view="full"><FilesFull data={data} /></div>
            <FilePreviewDialog request={preview} onClose={() => setPreview(null)} onOpenWorkflow={() => {}} />
        </DashboardActionsContext.Provider>;
    }
    const host = document.createElement('div');
    host.style.cssText = 'width:1200px;position:relative';
    document.body.appendChild(host);
    const root = createRoot(host);
    const click = (el: Element) => flushSync(() => nc.dom.click(el));
    const dialog = () => document.querySelector('[data-testid="dashboard-file-preview"]')!;
    try {
        flushSync(() => root.render(<Harness />));
        const compact = host.querySelector('[data-view="compact"]')!;
        nc.assert.equal(compact.querySelectorAll('[role="button"]').length, 3, 'All uploads appear in the bento');
        click(compact.querySelector('[role="button"]')!);
        await nc.wait.until(() => !!dialog()?.querySelector('img'), 3000);
        nc.assert.equal(dialog().querySelector('img')?.getAttribute('src'), files[0].files[0].url, 'Personal image previews inline');
        nc.assert.equal(dialog().querySelector('a[download]')?.getAttribute('href'), files[0].files[0].url, 'Download targets the attachment');
        nc.assert.falsy(dialog().textContent?.includes('Open workflow'), 'Account files have no fake workflow link');
        click([...dialog().querySelectorAll('button')].find((b) => b.textContent?.trim() === 'Close')!);
        await nc.wait.until(() => !dialog(), 3000);

        const full = host.querySelector('[data-view="full"]')!;
        // Filtering unfolds matching sources without changing session preferences.
        flushSync(() => nc.dom.type(full.querySelector('input')!, 'image.jpg'));
        const personal = full.querySelector('section')!;
        nc.assert.includes(personal.textContent ?? '', 'Personal files', 'Personal files have their own place');
        nc.assert.falsy([...personal.querySelectorAll('button')].some((b) => b.textContent === 'Upload'), 'No unsupported account upload action');
        const upload = [...full.querySelectorAll('button')].find((b) => b.textContent === 'Upload')!;
        click(upload);
        nc.assert.deepEqual(uploads, ['resources:workflow'], 'Workflow uploads remain available');
        click(personal.querySelector('[aria-label="Delete image.jpg"]')!);
        nc.assert.equal(deleted.length, 0, 'Deleting asks for confirmation');
        click([...personal.querySelectorAll('button')].find((b) => b.textContent === 'Delete')!);
        await nc.wait.until(() => personal.querySelectorAll('[aria-label="Delete image.jpg"]').length === 1, 3000);
        nc.assert.deepEqual(deleted, ['first'], 'Only the chosen resource is deleted');
        click(personal.querySelector('[role="button"]')!);
        await nc.wait.until(() => !!dialog()?.querySelector('img'), 3000);
        nc.assert.equal(dialog().querySelector('img')?.getAttribute('src'), files[0].files[1].url, 'The other same-named upload still opens correctly');
        return { preview: true, download: true, delete: true, duplicateNames: true };
    } finally {
        flushSync(() => root.unmount());
        host.remove();
    }
}
