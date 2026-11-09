import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const EventifyIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/eventify.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const EventifyNode: NodeDefinition = {
    type: 'automation-eventify', category: 'meetings', label: 'Eventify',
    description: 'Manage event attendees, sessions and speakers, and read exhibitors, sponsors and sales',
    Icon: EventifyIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={EventifyIcon} iconColor="" />),
};
