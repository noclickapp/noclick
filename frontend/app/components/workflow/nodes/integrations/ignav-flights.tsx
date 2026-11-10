/** Connects the Ignav Flights catalogue and canvas node. The backend schema supplies its flight search and booking-link actions. */
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const IgnavFlightsIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/ignav-flights.svg" dark="/icons/ignav-flights-dark.svg" className={className} style={style} />
);

export const IgnavFlightsNode: NodeDefinition = {
    type: 'automation-ignav-flights', category: 'bookings', label: 'Ignav Flights',
    description: 'Search flight fares and calendars, find airports and get seller booking links',
    Icon: IgnavFlightsIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={IgnavFlightsIcon} iconColor="" />),
};
