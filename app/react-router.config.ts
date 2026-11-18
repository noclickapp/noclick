import type { Config } from '@react-router/dev/config';

export default {
    appDirectory: 'src',
    ssr: true,
    // Middleware: the root route's gate (src/server/gate.server.ts) runs before every page, data request and the key
    // proxy.
    future: { v8_middleware: true },
} satisfies Config;
