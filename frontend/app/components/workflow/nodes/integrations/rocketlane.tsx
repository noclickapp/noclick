import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const RocketlaneIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/rocketlane.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const RocketlaneNode: NodeDefinition = {
    type: 'automation-rocketlane', category: 'productivity', label: 'Rocketlane',
    description: 'Manage projects, tasks, companies, phases and time entries',
    Icon: RocketlaneIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={RocketlaneIcon} iconColor="" />),
};
