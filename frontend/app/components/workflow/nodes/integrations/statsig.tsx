import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const StatsigIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/statsig.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const StatsigNode: NodeDefinition = {
    type: 'automation-statsig', category: 'developer-tools', label: 'Statsig',
    description: 'Manage feature gates, dynamic configs and tags; read experiments and segments',
    Icon: StatsigIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={StatsigIcon} iconColor="" />),
};
