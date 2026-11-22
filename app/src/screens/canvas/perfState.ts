// Global performance state for cross-component optimizations.
// When true, components should disable expensive effects (animations, blur, particles).

import { proxy } from 'valtio';

export const perfState = proxy({
    shouldOptimize: false,
});
