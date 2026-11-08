import type { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import type { NodeDefinition } from './types';
import ForgejoIcon from '~/components/icons/ForgejoIcon';
const ForgejoNodeComponent = (props: NodeProps) => (
    <AutomationNode {...props} Icon={ForgejoIcon as any} iconColor="" />
);
export const ForgejoNode: NodeDefinition = {
    type: 'automation-forgejo', category: 'developer-tools', label: 'Forgejo',
    description: 'Authenticated actor, repository and ordinary issue metadata on one Forgejo instance',
    keywords: ['Forgejo', 'repository metadata', 'issue status', 'self hosted git'],
    Icon: ForgejoIcon as any, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: ForgejoNodeComponent,
};
