import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const GiteaIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/gitea.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const GiteaNode: NodeDefinition = {
    type: 'automation-gitea', category: 'developer-tools', label: 'Gitea',
    description: 'Automate repositories, issues, pull requests, branches and releases',
    Icon: GiteaIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={GiteaIcon} iconColor="" />),
};
