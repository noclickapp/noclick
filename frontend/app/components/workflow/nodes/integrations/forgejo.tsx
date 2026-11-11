import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const ForgejoIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/forgejo.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);
const ForgejoNodeComponent = (props: NodeProps) => (
    <AutomationNode {...props} Icon={ForgejoIcon} iconColor="" />
);
export const ForgejoNode: NodeDefinition = {
    type: 'automation-forgejo', category: 'developer-tools', label: 'Forgejo',
    description: 'Authenticated actor, repository and ordinary issue metadata on one Forgejo instance',
    keywords: ['Forgejo', 'repository metadata', 'issue status', 'self hosted git'],
    Icon: ForgejoIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: ForgejoNodeComponent,
};
