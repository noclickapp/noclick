// ReactFlow nodeTypes for the canvas, each loading its node's definition when a node of the type is first drawn.
// Until it lands the node draws as its outline at its own size, with the catalog's icon, so the graph lays out
// and frames as it will look. Which types there are and what each draws as is the canvas's `canvas.step.drawing` slot.
import { useEffect, useRef, type ComponentType } from 'react';
import { useUpdateNodeInternals, type NodeProps, type NodeTypes } from '@xyflow/react';
import { standing, useSlot } from '@/slots';
import { SerializedIcon } from '@/ui/SerializedIcon';
import { STEP_DRAWING } from '../slots';
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
    const outline = useSlot(STEP_DRAWING).outline(type);
    const dims = outline?.dimensions;
    return (
        <div
            className="flex items-center justify-center rounded-2xl border border-border/40 bg-card dark:border-zinc-700/40"
            style={{ width: dims?.width ?? 90, height: dims?.height ?? 90 }}
            data-node-outline={type}
        >
            {outline?.iconHtml && (
                <SerializedIcon
                    html={outline.iconHtml}
                    iconColor={outline.iconColor}
                    style={{ width: dims?.iconSize ?? 48, height: dims?.iconSize ?? 48 }}
                />
            )}
        </div>
    );
}

function lazyNodeType(type: string): ComponentType<NodeProps> {
    const LazyNode = (props: NodeProps) => {
        const drawing = useSlot(STEP_DRAWING);
        const loaded = drawing.useLoaded([type]);
        const definition = loaded ? drawing.definition(type) : undefined;
        // React Flow reads a node's handles when it measures the node, and the outline has none. The node keeps
        // its size when its definition lands, so nothing re-measures it: its edges stay undrawn until told to.
        const updateNodeInternals = useUpdateNodeInternals();
        const drewOutline = useRef(false);
        useEffect(() => {
            if (!definition) drewOutline.current = true;
            else if (drewOutline.current) {
                drewOutline.current = false;
                updateNodeInternals(props.id);
            }
        }, [definition, props.id, updateNodeInternals]);
        if (!definition) return <NodeOutline type={type} />;
        const Component = componentFor(definition);
        return <Component {...props} />;
    };
    LazyNode.displayName = `LazyNode(${type})`;
    return LazyNode;
}

// Names asked of any object that are never a step's type: a promise's, JSON's and React's checks.
const NOT_TYPES = new Set(['then', 'toJSON', '$$typeof']);

/** nodeTypes for every node the canvas draws (legacy types by the node that replaced them), with
 *  `additionalTypes` taking priority (custom renderers with callbacks). Where the drawing names no list of types
 *  (`types: null`), any type is drawn as it's met: React Flow finds a node's type by its name alone. */
export function buildLazyNodeTypes(additionalTypes: NodeTypes = {}): NodeTypes {
    const { types: drawn } = standing(STEP_DRAWING);
    const types: NodeTypes = {};
    for (const type of drawn ?? []) types[type] = lazyNodeType(type);
    Object.assign(types, additionalTypes);
    if (drawn) return types;
    return new Proxy(types, {
        get(target, key) {
            if (typeof key !== 'string') return undefined;
            if (!(key in target) && !NOT_TYPES.has(key)) target[key] = lazyNodeType(key);
            return target[key];
        },
    });
}
