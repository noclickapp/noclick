// Zeeg scheduling and booking operations use the generated backend schema.
// This definition adds the integration to the canvas and public bookings catalog.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const ZeegIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/zeeg.svg" dark="/icons/zeeg-dark.svg" className={className} style={style} />
);

export const ZeegNode: NodeDefinition = {
    type: 'automation-zeeg', category: 'bookings', label: 'Zeeg',
    description: 'Manage scheduling pages, bookings, invitees, availability and internal notes',
    Icon: ZeegIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={ZeegIcon} iconColor="" />),
};
