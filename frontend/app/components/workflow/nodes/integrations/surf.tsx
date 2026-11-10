import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const SurfIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/surf.svg" dark="/icons/surf-dark.svg" className={className} style={style} />
);

export const SurfNode: NodeDefinition = {
    type: 'automation-surf', category: 'finance-accounting', label: 'Surf',
    description: 'Research crypto markets, projects, wallets and news, and manage onchain SQL jobs',
    Icon: SurfIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={SurfIcon} iconColor="" />),
};
