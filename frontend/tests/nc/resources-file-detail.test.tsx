// Exercise account files through the real Resources detail page. Two uploads
// share a filename, so each must resolve by its resource id; deletion is only
// armed, never confirmed, so the signed-in account stays untouched.
import { createRoot } from 'react-dom/client';
import { flushSync } from 'react-dom';
import { ResourceDetail } from '~/components/shell/resources/ResourceDetail';
import type { ResourceItem } from '~/components/shell/resources/model';
import type { FileSource } from '~/components/dashboard/types';
import { nc } from '~/lib/nc';

export default async function () {
    const imageUrl = (color: string) =>
        `data:image/svg+xml,${encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="40" height="40"><rect width="40" height="40" fill="${color}"/></svg>`)}`;
    const now = '2026-09-25T10:00:00Z';
    const source: FileSource = {
        id: 'resources:account',
        kind: 'resources',
        label: 'Personal files',
        sublabel: 'Uploads & attachments',
        writable: true,
        files: ['first', 'second'].map((id, i) => ({
            resourceId: id,
            path: 'image.jpg',
            kind: 'image',
            resourceType: 'image',
            mime: 'image/svg+xml',
            url: imageUrl(i ? 'blue' : 'red'),
            size: 100,
            mtime: now,
        })),
    };
    const items: ResourceItem[] = source.files.map((entry) => ({
        id: entry.resourceId!,
        kind: 'files',
        title: 'image.jpg',
        subtitle: source.label,
        updatedAt: entry.mtime,
        usedBy: [],
        file: { entry, source },
    }));
    const host = document.createElement('div');
    host.style.cssText = 'width:1200px;height:900px;position:relative';
    document.body.appendChild(host);
    const root = createRoot(host);
    const render = (item: ResourceItem) => flushSync(() => root.render(<ResourceDetail key={item.id} item={item} now={now} onBack={() => {}} onChanged={() => {}} />));
    const button = (text: string) => [...host.querySelectorAll('button')].find((b) => b.textContent?.trim() === text);
    const preview = () => host.querySelector('[data-testid="resource-detail"] section img')?.getAttribute('src');
    try {
        render(items[0]);
        await nc.wait.until(() => !!preview(), 3000);
        nc.assert.equal(preview(), items[0].file!.entry.url, 'An account image previews inline');
        nc.assert.equal(host.querySelector('a[download]')?.getAttribute('href'), items[0].file!.entry.url, 'Download targets the attachment');
        nc.assert.falsy([...host.querySelectorAll('h2')].some((h) => h.textContent?.startsWith('Used by')), 'Account files have no fake workflow link');

        flushSync(() => nc.dom.click(button('Delete')!));
        nc.assert.truthy(button('Delete file'), 'Deleting asks for confirmation first');
        flushSync(() => nc.dom.click(button('Cancel')!));
        nc.assert.truthy(button('Delete') && !button('Delete file'), 'Cancelling disarms the delete');

        render(items[1]);
        await nc.wait.until(() => preview() === items[1].file!.entry.url, 3000);
        return { preview: true, download: true, confirm: true, duplicateNames: true };
    } finally {
        flushSync(() => root.unmount());
        host.remove();
    }
}
