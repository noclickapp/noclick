import { memo } from 'react';
import type { CSSProperties } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
// Vector brand artwork from https://www.baseten.co.
const BasetenIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/baseten-brand-vector.svg" dark="/icons/baseten-brand-vector-dark.svg" className={className} style={style} />
);

const BasetenNodeComponent = (props: NodeProps) => (
    <AutomationNode {...props} Icon={BasetenIcon} iconColor="" />
);

export const BasetenNode: NodeDefinition = {
    type: 'automation-baseten',
    label: 'Baseten',
    description: 'Run Baseten model inference and inspect deployments',
    category: 'ai',
    keywords: ['baseten', 'AI', 'LLM', 'model', 'deployment', 'inference'],
    Icon: BasetenIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo(BasetenNodeComponent),
};
