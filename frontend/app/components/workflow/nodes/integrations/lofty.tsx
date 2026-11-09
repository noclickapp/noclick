import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const LoftyIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/lofty.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const LoftyNode: NodeDefinition = {
    type: 'automation-lofty', category: 'crm-sales', label: 'Lofty',
    description: 'Manage real estate leads, notes, tasks and client communication',
    Icon: LoftyIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={LoftyIcon} iconColor="" />),
};
