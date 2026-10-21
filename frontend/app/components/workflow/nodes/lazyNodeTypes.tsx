// ReactFlow nodeTypes for the canvas, each loading its node's definition when a node of the type is first drawn.
// Until it lands the node draws as its outline at its own size, with the catalog's icon, so the graph lays out
// and frames as it will look.
import type { ComponentType } from 'react';
import type { NodeProps, NodeTypes } from '@xyflow/react';
import { SerializedIcon } from '~/components/shared/SerializedIcon';
import { useNodeDefinitions } from '~/hooks/useNodeDefinitions';
import { getNodeIconMeta } from '~/lib/nodeIconRegistry';
import { LEGACY_NODE_TYPE_ALIASES } from '~/utils/nodeMeta';
import { NODE_DEFINITION_TYPES, getNodeDefinition, nodeDimensions } from './nodeDefinitions';
import { nodeTypeComponent } from './nodeTypeComponent';
import type { NodeDefinition } from './types';

const _components = new Map<NodeDefinition, ComponentType<NodeProps>>();
function componentFor(definition: NodeDefinition): ComponentType<NodeProps> {
    let component = _components.get(definition);
    if (!component) {
        component = nodeTypeComponent(definition);
        _components.set(definition, component);
    }
    return component;
}

function NodeOutline({ type }: { type: string }) {
    const dims = nodeDimensions(type);
    const meta = getNodeIconMeta(type);
    return (
        <div
            className="flex items-center justify-center rounded-2xl border border-border/40 bg-card dark:border-zinc-700/40"
            style={{ width: dims?.width ?? 90, height: dims?.height ?? 90 }}
            data-node-outline={type}
        >
            {meta?.iconHtml && (
                <SerializedIcon
                    html={meta.iconHtml}
                    iconColor={meta.iconColor}
                    style={{ width: dims?.iconSize ?? 48, height: dims?.iconSize ?? 48 }}
                />
            )}
        </div>
    );
}

function lazyNodeType(type: string): ComponentType<NodeProps> {
    const LazyNode = (props: NodeProps) => {
        const loaded = useNodeDefinitions([type]);
        const definition = loaded ? getNodeDefinition(type) : undefined;
        if (!definition) return <NodeOutline type={type} />;
        const Component = componentFor(definition);
        return <Component {...props} />;
    };
    LazyNode.displayName = `LazyNode(${type})`;
    return LazyNode;
}

/** nodeTypes for every node the canvas draws (legacy types by the node that replaced them), with
 *  `additionalTypes` taking priority (custom renderers with callbacks). */
export function buildLazyNodeTypes(additionalTypes: NodeTypes = {}): NodeTypes {
    const types: NodeTypes = {};
    for (const type of [...NODE_DEFINITION_TYPES, ...Object.keys(LEGACY_NODE_TYPE_ALIASES)]) types[type] = lazyNodeType(type);
    return Object.assign(types, additionalTypes);
}
