import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const EveryActionIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/everyaction.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain', '--brand-invert': 0 } as CSSProperties} />
);

export const EveryActionNode: NodeDefinition = {
    type: 'automation-everyaction', category: 'nonprofit', label: 'EveryAction',
    description: 'Find and update supporters, manage notes and event signups, and read contributions and saved lists.',
    keywords: ['NGP VAN', 'nonprofit', 'donors', 'volunteers', 'supporters'],
    Icon: EveryActionIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={EveryActionIcon} iconColor="" />),
};
