import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const RecraftIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/recraft.svg" dark="/icons/recraft-dark.svg" className={className} style={style} />
);

export const RecraftNode: NodeDefinition = {
    type: 'automation-recraft', category: 'ai', label: 'Recraft',
    description: 'Generate and edit raster and vector images, manage styles and read API credits',
    Icon: RecraftIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={RecraftIcon} iconColor="" />),
};
