import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const SimplicateIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/simplicate.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const SimplicateNode: NodeDefinition = {
    type: 'automation-simplicate', category: 'crm-sales', label: 'Simplicate',
    description: 'Read projects and services; manage relation types and sales service groups',
    Icon: SimplicateIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={SimplicateIcon} iconColor="" />),
};
