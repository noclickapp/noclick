import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const UnleashIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/unleash.svg" dark="/icons/unleash-dark.svg" className={className} style={style} />
);

export const UnleashNode: NodeDefinition = {
    type: 'automation-unleash', category: 'developer-tools', label: 'Unleash',
    description: 'Trigger workflows and agents from flag changes; manage feature flags, rollout strategies, environments and targeting segments',
    Icon: UnleashIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={UnleashIcon} iconColor="" />),
};
