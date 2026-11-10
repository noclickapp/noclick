import { memo } from 'react';
import type { CSSProperties } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition } from '~/components/workflow/nodes/types';

// Clockify mark from Simple Icons, rendered in its brand color.
const ClockifyIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img
        src="/icons/clockify.svg"
        alt=""
        aria-hidden="true"
        className={className}
        style={{ ...style, objectFit: 'contain' }}
    />
);

const ClockifyNodeComponent = (props: NodeProps) => (
    <AutomationNode {...props} Icon={ClockifyIcon} iconColor="" />
);

export const ClockifyNode: NodeDefinition = {
    type: 'automation-clockify',
    label: 'Clockify',
    description: 'Track time and manage projects, clients, tags and tasks',
    category: 'productivity',
    Icon: ClockifyIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo(ClockifyNodeComponent),
};
