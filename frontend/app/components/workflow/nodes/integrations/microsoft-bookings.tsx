// Microsoft Bookings adds business, appointment, customer, service and staff actions.
// This definition lets the integration catalog and workflow canvas discover the node.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const MicrosoftBookingsIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/microsoft-bookings.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const MicrosoftBookingsNode: NodeDefinition = {
    type: 'automation-microsoft-bookings', category: 'bookings', label: 'Microsoft Bookings',
    description: 'Manage Bookings appointments, customers and services; read businesses and staff',
    keywords: ['microsoft', 'bookings', 'appointments', 'scheduling', 'booking calendar'],
    Icon: MicrosoftBookingsIcon, iconColor: '#008272',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={MicrosoftBookingsIcon} iconColor="#008272" />),
};
