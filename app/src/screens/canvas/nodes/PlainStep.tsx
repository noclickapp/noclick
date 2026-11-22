// A step drawn from what's known of its type alone, where whoever renders the canvas has no drawing of its own for it
// (the standard of `canvas.step.drawing`): the catalog's glyph where the host loaded the catalog's icons (else a plain
// mark), its card (AutomationNode: a trigger's bolt in place of its input, a tool's handle on top, its error output),
// and a handle for each connection it holds that the card doesn't draw (a branch of a condition, an agent's tools
// coming in from below), so every connection the workflow has is drawn.
import type { CSSProperties } from 'react';
import { Handle, Position, useNodeConnections, type NodeProps } from '@xyflow/react';
import { Blocks } from 'lucide-react';
import { getNodeIconMeta } from '@/lib/nodeIconRegistry';
import { useSlot } from '@/slots';
import { SerializedIcon } from '@/ui/SerializedIcon';
import { STEP_ROLES } from '../slots';
import AutomationNode from './AutomationNode';
import { getNodeHandleLayout } from './nodeHandles';
import { getDefaultLabelFromType } from './NodeLabel';
import type { NodeDefinition, SvgIconComponent } from './types';

const HANDLE = '!w-4 !h-4 !bg-zinc-300 dark:!bg-zinc-400 !border-2 !border-zinc-400 dark:!border-zinc-500 transition-all opacity-70 hover:opacity-100';

const glyphs = new Map<string, SvgIconComponent>();

/** The type's glyph: the catalog's markup where it's loaded, else the plain mark. One component per type, so a step's
 *  icon is never remounted as it draws again. */
function glyphOf(type: string): SvgIconComponent {
    const html = getNodeIconMeta(type)?.iconHtml;
    if (!html) return Blocks as SvgIconComponent;
    let glyph = glyphs.get(html);
    if (!glyph) {
        const Drawn = ({ className, style }: { className?: string; style?: CSSProperties }) => <SerializedIcon html={html} className={className} style={style} />;
        glyphs.set(html, (glyph = Drawn as SvgIconComponent));
    }
    return glyph;
}

/** Spread `count` handles down a side, as a condition's branches are. */
const along = (index: number, count: number) => `${((index + 1) / (count + 1)) * 100}%`;

export function PlainStep(props: NodeProps) {
    const type = props.type ?? '';
    const roles = useSlot(STEP_ROLES).useRoles();
    const operation = (props.data as { operation?: string } | undefined)?.operation;
    const layout = getNodeHandleLayout(type, operation, undefined, roles);
    const errorOutput = ((props.data as { config?: { _settings?: { onError?: string } } } | undefined)?.config?._settings?.onError) === 'continueErrorOutput';
    const outgoing = useNodeConnections({ id: props.id, handleType: 'source' });
    const incoming = useNodeConnections({ id: props.id, handleType: 'target' });

    // What the card draws itself, by handle id (null: the step's one input or output).
    const cardSources = new Set<string | null>([...(layout.output ? [null] : []), ...(layout.output && errorOutput ? ['error'] : []), ...(layout.provider ? ['top'] : [])]);
    const cardTargets = new Set<string | null>(layout.input ? [null] : []);
    const extraSources = [...new Set(outgoing.map((c) => c.sourceHandle ?? null))].filter((id) => !cardSources.has(id));
    const extraTargets = [...new Set([...(layout.agentTarget ? ['bottom'] : []), ...incoming.map((c) => c.targetHandle ?? null)])].filter((id) => !cardTargets.has(id));
    const sideTargets = extraTargets.filter((id) => id !== 'bottom');
    const meta = getNodeIconMeta(type);

    return (
        <>
            <AutomationNode {...props} Icon={glyphOf(type)} iconColor={meta?.iconColor ?? ''} hideLeftHandle={!layout.input} hideRightHandle={!layout.output} />
            {extraSources.map((id, i) => (
                <Handle key={`s-${id ?? ''}`} id={id ?? undefined} type="source" position={Position.Right} className={HANDLE} style={{ top: along(i, extraSources.length), zIndex: 10 }} />
            ))}
            {extraTargets.includes('bottom') && <Handle id="bottom" type="target" position={Position.Bottom} className={HANDLE} style={{ zIndex: 10 }} />}
            {sideTargets.map((id, i) => (
                <Handle key={`t-${id ?? ''}`} id={id ?? undefined} type="target" position={Position.Left} className={HANDLE} style={{ top: along(i, sideTargets.length), zIndex: 10 }} />
            ))}
        </>
    );
}

const definitions = new Map<string, NodeDefinition>();

/** A type's plain drawing, as a node definition: its name and size from the catalog where it's loaded. One per type, so
 *  the canvas wraps each once. */
export function plainStepDefinition(type: string): NodeDefinition {
    let definition = definitions.get(type);
    if (!definition) {
        const meta = getNodeIconMeta(type);
        definition = {
            type,
            label: meta?.label || getDefaultLabelFromType(type),
            description: meta?.description ?? '',
            Icon: glyphOf(type),
            iconColor: meta?.iconColor ?? '',
            dimensions: meta?.dimensions ?? { width: 90, height: 90, iconSize: 48 },
            component: PlainStep,
        };
        definitions.set(type, definition);
    }
    return definition;
}
