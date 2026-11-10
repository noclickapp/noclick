import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const PenpotIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/penpot.svg" dark="/icons/penpot-dark.svg" className={className} style={style} />
);

export const PenpotNode: NodeDefinition = {
    type: 'automation-penpot', category: 'productivity', label: 'Penpot',
    description: 'Manage Penpot teams, projects, design files and shared libraries',
    keywords: ['design', 'prototype', 'designops'],
    Icon: PenpotIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={PenpotIcon} iconColor="" />),
};
