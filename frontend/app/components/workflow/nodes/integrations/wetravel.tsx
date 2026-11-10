/** Adds WeTravel to the workflow canvas and integration catalog.
 * Configuration and manual credential fields come from its generated schema. */
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const WeTravelIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/wetravel.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const WeTravelNode: NodeDefinition = {
    type: 'automation-wetravel', category: 'bookings', label: 'WeTravel',
    description: 'Manage trips, payment links and itinerary settings with the WeTravel Partner API',
    keywords: ['travel', 'tour', 'booking', 'payment link', 'itinerary'],
    Icon: WeTravelIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={WeTravelIcon} iconColor="" />),
};
