// Heartbeat canvas definition and provider mark. The integration is discovered
// automatically with its generated schema and credential metadata.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const HeartbeatIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/heartbeat.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const HeartbeatNode: NodeDefinition = {
    type: 'automation-heartbeat', category: 'courses', label: 'Heartbeat',
    description: 'Manage community members, groups, invitations, discussions and events',
    Icon: HeartbeatIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={HeartbeatIcon} iconColor="" />),
};
