import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const StibeeIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/stibee.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const StibeeNode: NodeDefinition = {
    type: 'automation-stibee', category: 'marketing', label: 'Stibee',
    description: 'Manage subscribers, groups, email drafts, sends and campaign statistics',
    Icon: StibeeIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={StibeeIcon} iconColor="" />),
};
