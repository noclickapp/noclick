// Bookingmood catalog and canvas definition. The shared automation UI renders its generated operation forms.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const BookingmoodIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/bookingmood.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const BookingmoodNode: NodeDefinition = {
    type: 'automation-bookingmood', category: 'bookings', label: 'Bookingmood',
    description: 'Manage bookings, guests, calendar events and housekeeping tasks',
    Icon: BookingmoodIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={BookingmoodIcon} iconColor="" />),
};
