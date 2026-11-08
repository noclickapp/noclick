import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const DeployHQIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/deployhq.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const DeployHQNode: NodeDefinition = {
    type: 'automation-deployhq', category: 'developer-tools', label: 'DeployHQ',
    description: 'Manage projects, deployments and schedules; inspect servers and repositories',
    Icon: DeployHQIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={DeployHQIcon} iconColor="" />),
};
