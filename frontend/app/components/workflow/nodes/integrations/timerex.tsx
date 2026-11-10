import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const TimeRexIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/timerex.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const TimeRexNode: NodeDefinition = {
    type: 'automation-timerex', category: 'bookings', label: 'TimeRex',
    description: 'Read teams, calendars and events; cancel bookings and create single-use scheduling links',
    Icon: TimeRexIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={TimeRexIcon} iconColor="" />),
};
