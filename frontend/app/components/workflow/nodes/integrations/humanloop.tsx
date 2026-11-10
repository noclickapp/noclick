import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const HumanloopIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/humanloop.svg" dark="/icons/humanloop-dark.svg" className={className} style={style} />
);

export const HumanloopNode: NodeDefinition = {
    type: 'automation-humanloop', category: 'ai', label: 'Humanloop',
    description: 'Manage prompts, datasets, evaluations, logs and directories',
    Icon: HumanloopIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={HumanloopIcon} iconColor="" />),
};
