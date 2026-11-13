import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';
import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';

const AirIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/air.svg" dark="/icons/air-dark.svg" className={className} style={style} />
);

export const AirNode: NodeDefinition = {
    type: 'automation-air', category: 'media', label: 'Air',
    description: 'Organize creative assets, boards and tags, import files, and watch for changes',
    keywords: ['digital asset management', 'creative', 'air.inc'],
    Icon: AirIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={AirIcon} iconColor="" />),
};
