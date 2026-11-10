import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const TinyfishIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/tinyfish.svg" dark="/icons/tinyfish-dark.svg" className={className} style={style} />
);

export const TinyfishNode: NodeDefinition = {
    type: 'automation-tinyfish', category: 'content-research', label: 'Tinyfish',
    description: 'Automate browser tasks, extract web content, research, and manage datasets and monitors',
    Icon: TinyfishIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={TinyfishIcon} iconColor="" />),
};
