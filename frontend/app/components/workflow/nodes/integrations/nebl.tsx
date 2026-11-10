import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const NeblioIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/nebl.svg" alt="" aria-hidden="true" className={className} style={{ ...style, objectFit: 'contain' }} />
);

export const NeblioNode: NodeDefinition = {
    type: 'automation-nebl',
    label: 'Neblio REST API Suite',
    category: 'developer-tools',
    description: 'Read the Neblio blockchain, build unsigned NTP1 token transactions, and broadcast signed transactions',
    keywords: ['NEBL', 'NTP1', 'blockchain', 'tokens', 'Insight', 'cryptocurrency'],
    Icon: NeblioIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={NeblioIcon} iconColor="" />),
};
