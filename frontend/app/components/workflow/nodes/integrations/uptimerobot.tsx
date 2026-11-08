// UptimeRobot canvas definition, discovered by the integration catalog.
// The brand mark identifies the service connected by this node.
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

// Official brand artwork from https://uptimerobot.com/.
const UptimeRobotIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/uptimerobot-brand-vector.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

const UptimeRobotNodeComponent = (props: NodeProps) => <AutomationNode {...props} Icon={UptimeRobotIcon} iconColor="" />;

export const UptimeRobotNode: NodeDefinition = {
    type: 'automation-uptimerobot',
    label: 'UptimeRobot',
    description: 'Monitor uptime, incidents, maintenance windows, and status pages',
    category: 'monitoring',
    Icon: UptimeRobotIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: UptimeRobotNodeComponent,
};
