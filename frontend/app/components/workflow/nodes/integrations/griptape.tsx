import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const GriptapeIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/griptape.svg" dark="/icons/griptape-dark.svg" className={className} style={style} />
);

export const GriptapeNode: NodeDefinition = {
    type: 'automation-griptape', category: 'ai', label: 'Griptape',
    description: 'Run structures and assistants, manage conversation memory, and query knowledge bases',
    Icon: GriptapeIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={GriptapeIcon} iconColor="" />),
};
