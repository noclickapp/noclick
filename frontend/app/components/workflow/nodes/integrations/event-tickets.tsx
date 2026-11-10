import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const EventTicketsIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/event-tickets.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const EventTicketsNode: NodeDefinition = {
    type: 'automation-event-tickets', category: 'bookings', label: 'Event Tickets',
    description: 'Find tickets, read attendees and update cart quantities on your WordPress site',
    keywords: ['The Events Calendar', 'WordPress', 'RSVP', 'tickets', 'attendees'],
    Icon: EventTicketsIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={EventTicketsIcon} iconColor="" />),
};
