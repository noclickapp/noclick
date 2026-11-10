import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const InvofoxIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/invofox.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const InvofoxNode: NodeDefinition = {
    type: 'automation-invofox', category: 'finance-accounting', label: 'Invofox',
    description: 'Extract invoice data, track imports, and manage companies, clients and providers',
    Icon: InvofoxIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={InvofoxIcon} iconColor="" />),
};
