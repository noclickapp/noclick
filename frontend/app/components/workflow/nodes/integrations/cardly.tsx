import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const CardlyIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/cardly.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const CardlyNode: NodeDefinition = {
    type: 'automation-cardly', label: 'Cardly',
    category: 'marketing',
    description: 'Manage contact lists and contacts, preview cards and place orders',
    Icon: CardlyIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={CardlyIcon} iconColor="" />),
};
