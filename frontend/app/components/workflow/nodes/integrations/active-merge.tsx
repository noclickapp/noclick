import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const ActiveMergeIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/active-merge.svg" dark="/icons/active-merge-dark.svg" className={className} style={style} />
);

export const ActiveMergeNode: NodeDefinition = {
    type: 'automation-active-merge', category: 'documents', label: 'Active Merge',
    description: 'Generate documents and images, merge files, send signatures, and manage templates',
    Icon: ActiveMergeIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={ActiveMergeIcon} iconColor="" />),
};
