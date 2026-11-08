import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const TimecampIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/timecamp.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const TimecampNode: NodeDefinition = {
    type: 'automation-timecamp', label: 'TimeCamp',
    category: 'productivity',
    description: 'Manage tasks, time entries, timers, users and tags',
    Icon: TimecampIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={TimecampIcon} iconColor="" />),
};
