import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const UplistingIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/uplisting.svg" dark="/icons/uplisting-dark.svg" className={className} style={style} />
);

export const UplistingNode: NodeDefinition = {
    type: 'automation-uplisting', category: 'bookings', label: 'Uplisting',
    description: 'Manage properties, availability, calendars, bookings, custom attributes and webhooks',
    Icon: UplistingIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={UplistingIcon} iconColor="" />),
};
