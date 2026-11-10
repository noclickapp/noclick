import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const EgnyteIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/egnyte.svg" dark="/icons/egnyte-dark.svg" className={className} style={style} />
);

export const EgnyteNode: NodeDefinition = {
    type: 'automation-egnyte', category: 'databases-storage', label: 'Egnyte',
    description: 'Start workflows from file uploads; manage files, folders, sharing links, comments and events',
    Icon: EgnyteIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={EgnyteIcon} iconColor="" />),
};
