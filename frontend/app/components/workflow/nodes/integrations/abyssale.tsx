import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const AbyssaleIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/abyssale.svg" dark="/icons/abyssale-dark.svg" className={className} style={style} />
);

export const AbyssaleNode: NodeDefinition = {
    type: 'automation-abyssale', label: 'Abyssale',
    category: 'media',
    description: 'Generate creative assets and manage Abyssale designs, projects and templates',
    Icon: AbyssaleIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={AbyssaleIcon} iconColor="" />),
};
