import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const TemplatedIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/templated.svg" dark="/icons/templated-dark.svg" className={className} style={style} />
);

export const TemplatedNode: NodeDefinition = {
    type: 'automation-templated', label: 'Templated',
    category: 'media',
    description: 'Generate images and PDFs and manage templates, renders, folders, uploads and fonts',
    Icon: TemplatedIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={TemplatedIcon} iconColor="" />),
};
