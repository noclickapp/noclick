import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const LakeraGuardIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/lakera-guard.svg" dark="/icons/lakera-guard-dark.svg" className={className} style={style} />
);

export const LakeraGuardNode: NodeDefinition = {
    type: 'automation-lakera-guard', category: 'ai', label: 'Lakera Guard',
    description: 'Screen LLM content and tool definitions, inspect detection results and check policy health',
    Icon: LakeraGuardIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={LakeraGuardIcon} iconColor="" />),
};
