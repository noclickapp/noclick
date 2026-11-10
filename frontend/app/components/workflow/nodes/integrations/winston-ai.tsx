import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const WinstonAIIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/winston-ai.svg" dark="/icons/winston-ai-dark.svg" className={className} style={style} />
);

export const WinstonAINode: NodeDefinition = {
    type: 'automation-winston-ai', category: 'ai', label: 'Winston AI',
    description: 'Detect AI content and images, check plagiarism and facts, and compare texts',
    keywords: ['winston', 'AI detection', 'plagiarism', 'fact checker', 'forensics'],
    Icon: WinstonAIIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={WinstonAIIcon} iconColor="" />),
};
