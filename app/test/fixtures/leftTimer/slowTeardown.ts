// happy-dom, with a teardown that waits after taking the window away: a timer a file left fires then, as one does in the
// moment between a real file's teardown and its worker ending.
import { builtinEnvironments, type Environment } from 'vitest/runtime';

export default <Environment>{
    name: 'slow-teardown',
    viteEnvironment: 'client',
    async setup(global, options) {
        const env = await builtinEnvironments['happy-dom'].setup(global, options);
        return {
            async teardown(g) {
                await env.teardown(g);
                await new Promise((resolve) => setTimeout(resolve, 1200));
            },
        };
    },
};
