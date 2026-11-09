import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const ParmaIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/parma.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const ParmaNode: NodeDefinition = {
    type: 'automation-parma', category: 'crm-sales', label: 'Parma',
    description: 'Manage CRM relationships, notes and groups; read deals and pipelines',
    Icon: ParmaIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={ParmaIcon} iconColor="" />),
};
