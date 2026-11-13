// Registers Bluepillow in the self-discovered integration catalog and canvas.
// The official B2A icon identifies its travel search and booking-link operations.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const BluepillowIcon = ({
    className,
    style,
}: {
    className?: string;
    style?: CSSProperties;
}) => (
    <ThemedBrandImg light="/icons/bluepillow.svg" className={className} style={style} />
);

export const BluepillowNode: NodeDefinition = {
    type: 'automation-bluepillow',
    category: 'bookings',
    label: 'Bluepillow',
    description:
        'Find stays, compare offers, resolve destinations and create booking links',
    Icon: BluepillowIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo(function BluepillowComponent(props: NodeProps) {
        return <AutomationNode {...props} Icon={BluepillowIcon} iconColor="" />;
    }),
};
