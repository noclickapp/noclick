import { reactRouter } from '@react-router/dev/vite';
import { defineConfig } from 'vite';
import tsconfigPaths from 'vite-tsconfig-paths';
import mdx from '@mdx-js/rollup';
import commonjs from 'vite-plugin-commonjs';
import { ncPlugin } from './app/lib/nc/vite-plugin';
import path from 'path';

// Chunk filenames derive from source filenames, and names like
// analytics-events-<hash>.js match generic EasyPrivacy/EasyList patterns —
// uBlock Origin blocks the chunk and every lazy import that depends on it
// dies (dead nav links, auth modal, white-flash reload loop on the landing
// page). Neutralize any chunk whose name contains ad-blocker bait.
const ADBLOCK_BAIT = /analytic|telemetr|track|pixel|beacon|banner|advert|sponsor|gtag|gtm|doubleclick|adsense|affiliate|popunder|^ads?[-_.]|[-_.]ads?[-_.]/i;
// Route modules are rollup entries (React Router registers each route as an input),
// shared/lazy modules are chunks — both need the sanitized name.
const neutralizeBaitName = (info: { name: string }) =>
    ADBLOCK_BAIT.test(info.name) ? 'assets/chunk-[hash].js' : 'assets/[name]-[hash].js';

export default defineConfig({
    plugins: [
        ncPlugin(),
        mdx(),
        commonjs(),
        reactRouter(),
        tsconfigPaths(),
    ],
    resolve: {
        alias: {
            '~': path.resolve(__dirname, './app'),
        },
        // Deduplicate React to prevent multiple instances causing null reference errors
        dedupe: ['react', 'react-dom'],
    },
    define: {
        global: 'globalThis',
    },
    build: {
        rollupOptions: {
            output: {
                entryFileNames: neutralizeBaitName,
                chunkFileNames: neutralizeBaitName,
                assetFileNames: (info) =>
                    ADBLOCK_BAIT.test(info.names?.[0] ?? '')
                        ? 'assets/asset-[hash][extname]'
                        : 'assets/[name]-[hash][extname]',
            },
        },
    },
    optimizeDeps: {
        exclude: [
            'util',
            'stream-slice',
            'fs',
            'path',
            'crypto',
        ],
        // Include React to ensure it's pre-bundled and available early
        // Include react-grid-layout and its deps to prevent duplicate React instances
        // html-to-image is lazily imported by the thumbnail generator's PNG export;
        // pre-bundling it avoids the "outdated optimize dep" fetch failure.
        include: ['react', 'react-dom', 'react-grid-layout', 'react-grid-layout/extras', 'react-draggable', 'react-resizable', 'html-to-image'],
    },
    ssr: {
        noExternal: ['@visx/vendor', '@lobehub/icons', '@lobehub/ui', '@lobehub/fluent-emoji'],
    },
    server: {
        allowedHosts: [
            '.ngrok-free.app',
            '.ngrok.io',
            '.ngrok-free.dev',
            '.trycloudflare.com',
            '.loca.lt',
            '.localtunnel.me',
        ],
        // Dev-only proxy so client-side fetches to /api/public/* (e.g. /forkflow fetching
        // a workflow) reach the configured backend. Scoped narrowly to /api/public so it
        // doesn't shadow the framework's /api/auth/* routes. Honors VITE_API_URL — if you started
        // dev with VITE_API_URL=http://localhost:8002 it forwards there.
        proxy: {
            // Trailing slash: proxy keys are PREFIXES, and the bare
            // '/api/public' also captured Remix's /api/public-session
            // resource route — every marketing nav read as logged out in
            // dev because the session fetch 404'd against uvicorn.
            '/api/public/': process.env.VITE_API_URL || 'http://localhost:8000',
        },
        // Allow imports from the sibling backend/ dir so the FE can read
        // auto-refreshed catalogs that live alongside Pydantic configs
        // (e.g. backend/nodes/agent/config/_cli_models.json — refreshed daily
        // by .github/workflows/refresh-cli-models.yml). Build-time inlines the
        // JSON; this only loosens dev-server fs serving.
        fs: {
            allow: [path.resolve(__dirname, '..')],
        },
        watch: {
            ignored: ['**/sdk/**'],
        },
    },
});
