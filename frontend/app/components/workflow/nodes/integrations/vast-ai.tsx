// Vast.ai provides GPU rentals and persistent storage for compute workflows.
// This definition discovers its generated schema and identifies the provider on the canvas.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const VastAiIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/vast-ai.svg" dark="/icons/vast-ai-dark.svg" className={className} style={style} />
);

export const VastAiNode: NodeDefinition = {
    type: 'automation-vast-ai', category: 'cloud-hosting', label: 'Vast Ai',
    description: 'Search GPU offers, manage instances, rent volumes and read billing',
    keywords: ['vast.ai', 'vastai', 'GPU', 'cloud', 'compute'],
    Icon: VastAiIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={VastAiIcon} iconColor="" />),
};
