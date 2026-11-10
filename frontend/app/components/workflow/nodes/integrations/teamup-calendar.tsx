import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const TeamupCalendarIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/teamup-calendar.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const TeamupCalendarNode: NodeDefinition = {
    type: 'automation-teamup-calendar', category: 'productivity', label: 'Teamup Calendar',
    description: 'Manage calendar events, sub-calendars, comments and signups',
    Icon: TeamupCalendarIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={TeamupCalendarIcon} iconColor="" />),
};
