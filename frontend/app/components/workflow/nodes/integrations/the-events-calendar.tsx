import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const TheEventsCalendarIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/the-events-calendar.svg" dark="/icons/the-events-calendar-dark.svg" className={className} style={style} />
);

export const TheEventsCalendarNode: NodeDefinition = {
    type: 'automation-the-events-calendar', category: 'bookings', label: 'The Events Calendar',
    description: 'Find, update and delete WordPress events, venues, organizers, categories and tags',
    keywords: ['WordPress', 'Tribe', 'events', 'calendar'],
    Icon: TheEventsCalendarIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={TheEventsCalendarIcon} iconColor="" />),
};
