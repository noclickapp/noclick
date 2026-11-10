import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const FilevineIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/filevine.svg" dark="/icons/filevine-dark.svg" className={className} style={style} />
);

export const FilevineNode: NodeDefinition = {
    type: 'automation-filevine', category: 'industry', label: 'Filevine',
    description: 'Start workflows from case, contact and task events; manage Filevine records',
    Icon: FilevineIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={FilevineIcon} iconColor="" />),
};
