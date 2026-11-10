// Scheduleonce exposes the OnceHub booking and contact API in the workflow editor.
// This definition supplies its catalog category and the provider's official icon.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const ScheduleonceIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/scheduleonce.svg" dark="/icons/scheduleonce-dark.svg" className={className} style={style} />
);

export const ScheduleonceNode: NodeDefinition = {
    type: 'automation-scheduleonce', category: 'bookings', label: 'Scheduleonce',
    description: 'Manage OnceHub bookings, availability, contacts and scheduling links',
    keywords: ['OnceHub', 'ScheduleOnce', 'appointments', 'scheduling'],
    Icon: ScheduleonceIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={ScheduleonceIcon} iconColor="" />),
};
