import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const InfisicalIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/infisical.svg" dark="/icons/infisical-dark.svg" className={className} style={style} />
);

export const InfisicalNode: NodeDefinition = {
    type: 'automation-infisical', category: 'developer-tools', label: 'Infisical',
    description: 'Manage secrets, folders, projects, environments and tags',
    Icon: InfisicalIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={InfisicalIcon} iconColor="" />),
};
