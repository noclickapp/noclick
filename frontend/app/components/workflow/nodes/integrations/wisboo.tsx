import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const WisbooIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/wisboo.svg" className={className} style={style} />
);

export const WisbooNode: NodeDefinition = {
    type: 'automation-wisboo', category: 'courses', label: 'Wisboo',
    description: 'Manage students, purchases and products, grant course access, and trigger on new accesses',
    keywords: ['courses', 'students', 'enrollment', 'learning'],
    Icon: WisbooIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={WisbooIcon} iconColor="" />),
};
