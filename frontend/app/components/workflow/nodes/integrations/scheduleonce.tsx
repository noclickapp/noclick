// Scheduleonce exposes the OnceHub booking and contact API in the workflow editor.
// This definition supplies its catalog category and the provider's official icon.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const ScheduleonceIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <>
        <img src="/icons/scheduleonce.svg" alt="" aria-hidden="true" className={`${className ?? ''} dark:hidden`}
            style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
        <img src="/icons/scheduleonce-dark.svg" alt="" aria-hidden="true" className={`${className ?? ''} hidden dark:block`}
            style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
    </>
);

export const ScheduleonceNode: NodeDefinition = {
    type: 'automation-scheduleonce', category: 'bookings', label: 'Scheduleonce',
    description: 'Manage OnceHub bookings, availability, contacts and scheduling links',
    keywords: ['OnceHub', 'ScheduleOnce', 'appointments', 'scheduling'],
    Icon: ScheduleonceIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={ScheduleonceIcon} iconColor="" />),
};
