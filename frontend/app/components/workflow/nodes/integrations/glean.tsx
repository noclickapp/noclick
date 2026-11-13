// Glean connects enterprise search, curated knowledge and signed preset events.
// This definition makes the integration discoverable in the canvas and catalog.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';
import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';

const GleanIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/glean.svg" className={className} style={style} />
);

export const GleanNode: NodeDefinition = {
    type: 'automation-glean',
    category: 'content-research',
    label: 'Glean',
    description:
        'Search company knowledge, manage collections, answers and Go Links, and receive preset events',
    keywords: ['enterprise search', 'knowledge', 'go links', 'webhook'],
    Icon: GleanIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => (
        <AutomationNode {...props} Icon={GleanIcon} iconColor="" />
    )),
};
