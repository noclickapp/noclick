import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const FleetioIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/fleetio.svg" dark="/icons/fleetio-dark.svg" className={className} style={style} />
);

export const FleetioNode: NodeDefinition = {
    type: 'automation-fleetio', category: 'industry', label: 'Fleetio',
    description: 'Manage fleet records and start workflows from vehicle, issue, fuel and service events',
    Icon: FleetioIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={FleetioIcon} iconColor="" />),
};
