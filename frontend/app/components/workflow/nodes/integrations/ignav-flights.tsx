/** Connects the Ignav Flights catalogue and canvas node. The backend schema supplies its flight search and booking-link actions. */
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const IgnavFlightsIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/ignav-flights.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const IgnavFlightsNode: NodeDefinition = {
    type: 'automation-ignav-flights', category: 'bookings', label: 'Ignav Flights',
    description: 'Search flight fares and calendars, find airports and get seller booking links',
    Icon: IgnavFlightsIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={IgnavFlightsIcon} iconColor="" />),
};
