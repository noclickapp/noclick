import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const ApiframeIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/apiframe.svg" dark="/icons/apiframe-dark.svg" className={className} style={style} />
);

export const ApiframeNode: NodeDefinition = {
    type: 'automation-apiframe', category: 'ai', label: 'Apiframe',
    description: 'Generate and edit images, video and music; track jobs and manage LoRAs',
    Icon: ApiframeIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={ApiframeIcon} iconColor="" />),
};
