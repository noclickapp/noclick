import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const PerfectVenueIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/perfect-venue.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const PerfectVenueNode: NodeDefinition = {
    type: 'automation-perfect-venue', category: 'bookings', label: 'Perfect Venue',
    description: 'Manage venue events and contacts, sync bookings and read team members',
    Icon: PerfectVenueIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={PerfectVenueIcon} iconColor="" />),
};
