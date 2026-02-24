// Vite build config for standalone MCP Apps widgets.
// Produces a single self-contained HTML file (all JS/CSS/ReactFlow inlined)
// using vite-plugin-singlefile. Output goes to backend/mcp_adapter/html_widgets/dist/.

import { defineConfig, type Plugin } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from 'tailwindcss';
import autoprefixer from 'autoprefixer';
import { viteSingleFile } from 'vite-plugin-singlefile';
import path from 'path';
import fs from 'fs';

const frontendDir = path.resolve(__dirname, '..');
const stubsPath = path.resolve(__dirname, 'stubs.ts');
const widgetBlockRendererPath = path.resolve(__dirname, 'WidgetBlockRenderer.tsx');
const publicIconsDir = path.resolve(frontendDir, 'public', 'icons');

// Inline /icons/*.svg references as data URIs at build time.
// Node components render <img src="/icons/slack.svg"> which would 404 inside
// the widget iframe (hosted on ChatGPT/MCP Inspector's origin). This plugin
// replaces those string literals with base64 data URIs so icons load instantly
// with no network requests and no CORS issues.
function inlinePublicIcons(): Plugin {
    return {
        name: 'inline-public-icons',
        enforce: 'pre',
        transform(code, id) {
            if (!id.match(/\.(tsx?|jsx?)$/)) return;
            if (!code.includes('/icons/')) return;
            return code.replace(
                /["']\/icons\/([\w.-]+\.svg)["']/g,
                (_match, filename: string) => {
                    const svgPath = path.resolve(publicIconsDir, filename);
                    if (!fs.existsSync(svgPath)) return _match;
                    const svg = fs.readFileSync(svgPath, 'utf-8');
                    const b64 = Buffer.from(svg).toString('base64');
                    return `"data:image/svg+xml;base64,${b64}"`;
                },
            );
        },
    };
}

// Stub app-specific runtime modules that the node component tree imports
// but are irrelevant in a read-only widget context. These must be listed
// BEFORE the general '~' alias so they take priority in resolution order.
const stubModules = [
    '~/lib/perf-state',
    '~/components/workflow/collaboration/CollaborativeContext',
    '~/components/workflow/collaboration',
    '~/lib/collaboration',
    '~/components/workflow/WorkflowContext',
    '~/hooks/useModels',
    '~/hooks/useOpenRouterModels',
    '~/hooks/useLiteLLMModels',
    '~/hooks/useDrawer',
    '~/hooks/useAPIKeys',
    '~/hooks/useCachedValtioState',
    '~/hooks/useValtioState',
    '~/hooks/useResourceUpload',
    '~/hooks/useMediaResource',
    '~/components/chat/ModelDropdown',
    '~/components/chat/MarkdownRenderer',
    '~/components/workflow/IODataDisplay',
    '~/lib/socket-sender',
    '~/lib/socket',
    '~/lib/socketClient',
];

// Array format guarantees resolution order: specific stubs first, then general '~' alias
const aliasEntries = [
    ...stubModules.map((mod) => ({ find: mod, replacement: stubsPath })),
    { find: '~/components/interface/BlockRenderer', replacement: widgetBlockRendererPath },
    { find: '~', replacement: path.resolve(frontendDir, 'app') },
];

export default defineConfig({
    root: path.resolve(__dirname, 'workflow-viewer'),
    plugins: [inlinePublicIcons(), react(), viteSingleFile()],
    css: {
        postcss: {
            plugins: [
                tailwindcss({
                    config: path.resolve(frontendDir, 'tailwind.config.ts'),
                }),
                autoprefixer(),
            ],
        },
    },
    resolve: {
        alias: aliasEntries,
        dedupe: ['react', 'react-dom'],
    },
    build: {
        outDir: path.resolve(frontendDir, '..', 'backend', 'mcp_adapter', 'html_widgets', 'dist'),
        emptyOutDir: true,
        // Inline all assets for singlefile
        assetsInlineLimit: Infinity,
        rollupOptions: {
            input: path.resolve(__dirname, 'workflow-viewer', 'workflow-viewer.html'),
        },
    },
    define: {
        // Ensure process.env references don't break
        'process.env': '{}',
    },
});
