// The node config form loads with the first node opened (its widgets bring CodeMirror, its checks Ajv), so the
// canvas draws without it; preloadNodeConfig warms it once the canvas is idle.
import { lazy, Suspense } from 'react';
import type { NodeConfigProps } from './NodeConfig';

const importNodeConfig = () => import('./NodeConfig');
const NodeConfigImpl = lazy(() => importNodeConfig().then((m) => ({ default: m.NodeConfig })));

/** Warm the config form's chunk. */
export function preloadNodeConfig(): void {
    void importNodeConfig();
}

export function NodeConfig(props: NodeConfigProps) {
    return (
        <Suspense fallback={null}>
            <NodeConfigImpl {...props} />
        </Suspense>
    );
}
