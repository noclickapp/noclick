import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const ArboxIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/arbox.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const ArboxNode: NodeDefinition = {
    type: 'automation-arbox', category: 'industry', label: 'Arbox',
    description: 'Manage fitness business leads, users, tasks, schedules and memberships',
    Icon: ArboxIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={ArboxIcon} iconColor="" />),
};
