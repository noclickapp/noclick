// Vite build config for standalone MCP Apps widgets.
// Produces a single self-contained HTML file (all JS/CSS/ReactFlow inlined)
// using vite-plugin-singlefile. Output goes to backend/mcp_adapter/html_widgets/dist/.

import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from 'tailwindcss';
import autoprefixer from 'autoprefixer';
import { viteSingleFile } from 'vite-plugin-singlefile';
import path from 'path';

const frontendDir = path.resolve(__dirname, '..');
const stubsPath = path.resolve(__dirname, 'stubs.ts');

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
    '~/lib/socket',
    '~/lib/socketClient',
];

// Array format guarantees resolution order: specific stubs first, then general '~' alias
const aliasEntries = [
    ...stubModules.map((mod) => ({ find: mod, replacement: stubsPath })),
    { find: '~', replacement: path.resolve(frontendDir, 'app') },
];

export default defineConfig({
    root: path.resolve(__dirname, 'workflow-viewer'),
    plugins: [react(), viteSingleFile()],
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
