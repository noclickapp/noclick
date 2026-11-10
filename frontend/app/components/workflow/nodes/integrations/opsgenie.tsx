import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const OpsGenieIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/opsgenie.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const OpsGenieNode: NodeDefinition = {
    type: 'automation-opsgenie', category: 'monitoring', label: 'OpsGenie',
    description: 'Manage alerts, teams, on-call schedules and heartbeats',
    Icon: OpsGenieIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={OpsGenieIcon} iconColor="" />),
};
