// Live render test for the universal FileBlock (the interface File node's UI).
// Mounts the block in isolation (inside a ReactFlowProvider, which useMediaResource's
// useStore needs) with a mocked execution output for each media kind, and asserts the
// block routes to the correct viewer: <img>, <video>, waveform audio, <iframe> for PDF,
// or a download card for anything else. Also covers the extension-fallback path
// (detectKind, used when the backend didn't stamp output.type) and the empty drop zone.
//
// Media elements (img/video/audio) swap to an inline error view when their source
// fails to load — that's the surfacing behavior we added — so for those kinds we
// assert "the correct branch was taken" (primary element OR its error text) and that
// no OTHER kind's element rendered, which is timing-robust in a headless tab.
//
// Run: mcp__nc__nc_run_test({ file: "tests/nc/interface-file-block-render.test.ts" })

import { nc } from '~/lib/nc';
import * as React from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { ReactFlowProvider } from '@xyflow/react';
import { FileBlock } from '~/components/interface/blocks/FileBlock';

const h = React.createElement;

// 1x1 transparent PNG — loads successfully so the image branch doesn't flip to error.
const PNG_DATA_URL =
    'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M8AAAMBAQDJ/pLvAAAAAElFTkSuQmCC';

async function mount(
    output: Record<string, unknown> | null,
    config: Record<string, unknown> = {},
): Promise<{ container: HTMLElement; cleanup: () => void }> {
    const container = document.createElement('div');
    container.style.cssText = 'position:fixed;left:-9999px;top:0;width:400px;height:300px';
    document.body.appendChild(container);
    const root: Root = createRoot(container);
    root.render(
        h(
            ReactFlowProvider,
            null,
            h(FileBlock as any, {
                id: 'nc-file-test',
                config,
                output,
                isSelected: false,
                onConfigChange: () => {},
            }),
        ),
    );
    // Let React 19 commit + a couple frames pass so the branch is in the DOM.
    await nc.wait.ms(120);
    return {
        container,
        cleanup: () => {
            root.unmount();
            container.remove();
        },
    };
}

const has = (c: HTMLElement, sel: string) => !!c.querySelector(sel);
const text = (c: HTMLElement) => (c.textContent || '').toLowerCase();

export default async function () {
    const results: Record<string, unknown> = {};

    // ── image (execution output stamps type) ──────────────────────────────
    {
        const { container, cleanup } = await mount({ url: PNG_DATA_URL, type: 'image' });
        const img = container.querySelector('img') as HTMLImageElement | null;
        nc.assert.truthy(img, 'image output → <img> element');
        nc.assert.equal(img!.getAttribute('src'), PNG_DATA_URL, 'img src matches output url');
        nc.assert.falsy(has(container, 'video, iframe'), 'image branch has no video/iframe');
        results.image = { img: !!img };
        cleanup();
    }

    // ── video ─────────────────────────────────────────────────────────────
    {
        const url = 'https://cdn.example.io/clip.mp4';
        const { container, cleanup } = await mount({ url, type: 'video' });
        const ok = has(container, 'video') || text(container).includes('video');
        nc.assert.truthy(ok, 'video output → <video> (or its load-error view)');
        nc.assert.falsy(has(container, 'img, iframe'), 'video branch has no img/iframe');
        results.video = { video: has(container, 'video'), erroredToText: text(container).includes('could not') };
        cleanup();
    }

    // ── audio (waveform player) ───────────────────────────────────────────
    {
        const url = 'https://cdn.example.io/song.mp3';
        const { container, cleanup } = await mount({ url, type: 'audio' });
        const ok = has(container, 'button') || text(container).includes('audio');
        nc.assert.truthy(ok, 'audio output → play button (or its load-error view)');
        nc.assert.falsy(has(container, 'img, video, iframe'), 'audio branch has no img/video/iframe');
        results.audio = { button: has(container, 'button') };
        cleanup();
    }

    // ── pdf (iframe embed) ────────────────────────────────────────────────
    {
        const url = 'https://cdn.example.io/report.pdf';
        const { container, cleanup } = await mount({ url, type: 'pdf' });
        const iframe = container.querySelector('iframe') as HTMLIFrameElement | null;
        nc.assert.truthy(iframe, 'pdf output → <iframe>');
        nc.assert.equal(iframe!.getAttribute('src'), url, 'iframe src matches output url');
        nc.assert.falsy(has(container, 'img, video'), 'pdf branch has no img/video');
        results.pdf = { iframe: !!iframe };
        cleanup();
    }

    // ── generic file (download card) ──────────────────────────────────────
    {
        const url = 'https://cdn.example.io/data.csv';
        const { container, cleanup } = await mount({ url, type: 'file', file_name: 'data.csv' });
        const link = container.querySelector('a[href]') as HTMLAnchorElement | null;
        nc.assert.truthy(link, 'generic file → download <a>');
        nc.assert.equal(link!.getAttribute('href'), url, 'download href matches url');
        nc.assert.truthy(text(container).includes('data.csv'), 'shows the file name');
        nc.assert.falsy(has(container, 'img, video, iframe'), 'download card has no media element');
        results.file = { link: !!link };
        cleanup();
    }

    // ── extension fallback: output has a url but NO type (detectKind) ──────
    {
        // .png url, no type → detectKind must resolve image and render <img>.
        const { container, cleanup } = await mount({ url: PNG_DATA_URL });
        // A data URL has no extension, so seed config.mimeType so detectKind resolves image.
        cleanup();
        const { container: c2, cleanup: cl2 } = await mount(
            { url: PNG_DATA_URL },
            { mimeType: 'image/png' },
        );
        nc.assert.truthy(has(c2, 'img'), 'no output.type + image mime → detectKind picks <img>');
        results.detectKindFallback = { img: has(c2, 'img') };
        cl2();
        void container;
    }

    // ── empty state: no output, no resource → drop zone with file input ────
    {
        const { container, cleanup } = await mount(null, {});
        const input = container.querySelector('input[type="file"]') as HTMLInputElement | null;
        nc.assert.truthy(input, 'empty block → file input present');
        nc.assert.falsy(input!.hasAttribute('accept'), 'accepts ANY file (no accept filter)');
        nc.assert.truthy(text(container).includes('drop a file'), 'shows drop prompt');
        results.empty = { input: !!input, acceptAny: !input!.hasAttribute('accept') };
        cleanup();
    }

    return { ok: true, results };
}
