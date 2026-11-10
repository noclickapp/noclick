// Conductor's catalog and canvas definition use the shared automation renderer.
// Its schema and credential metadata are generated from the backend node.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const ConductorIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/conductor.svg" dark="/icons/conductor-dark.svg" className={className} style={style} />
);

export const ConductorNode: NodeDefinition = {
    type: 'automation-conductor', category: 'developer-tools', label: 'Conductor',
    description: 'Manage cloud workspaces, coding sessions and agent messages',
    Icon: ConductorIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={ConductorIcon} iconColor="" />),
};
