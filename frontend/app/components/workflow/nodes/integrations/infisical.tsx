import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const InfisicalIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/infisical.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const InfisicalNode: NodeDefinition = {
    type: 'automation-infisical', category: 'developer-tools', label: 'Infisical',
    description: 'Manage secrets, folders, projects, environments and tags',
    Icon: InfisicalIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={InfisicalIcon} iconColor="" />),
};
