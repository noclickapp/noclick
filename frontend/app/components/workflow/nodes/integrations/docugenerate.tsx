import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const DocugenerateIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/docugenerate.svg" dark="/icons/docugenerate-dark.svg" className={className} style={style} />
);

export const DocugenerateNode: NodeDefinition = {
    type: 'automation-docugenerate', label: 'DocuGenerate',
    category: 'documents',
    description: 'Create templates and generate, manage and retrieve documents',
    Icon: DocugenerateIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={DocugenerateIcon} iconColor="" />),
};
