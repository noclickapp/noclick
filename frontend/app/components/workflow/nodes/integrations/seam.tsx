import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const SeamIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/seam.svg" dark="/icons/seam-dark.svg" className={className} style={style} />
);

export const SeamNode: NodeDefinition = {
    type: 'automation-seam', category: 'developer-tools', label: 'Seam',
    description: 'Manage smart locks, devices, access codes and connected accounts',
    Icon: SeamIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={SeamIcon} iconColor="" />),
};
