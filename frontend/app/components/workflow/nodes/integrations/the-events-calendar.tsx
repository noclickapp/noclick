import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const TheEventsCalendarIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/the-events-calendar.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const TheEventsCalendarNode: NodeDefinition = {
    type: 'automation-the-events-calendar', category: 'bookings', label: 'The Events Calendar',
    description: 'Find, update and delete WordPress events, venues, organizers, categories and tags',
    keywords: ['WordPress', 'Tribe', 'events', 'calendar'],
    Icon: TheEventsCalendarIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={TheEventsCalendarIcon} iconColor="" />),
};
