import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';
import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';

const SpydraIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/spydra.svg" dark="/icons/spydra-dark.svg" className={className} style={{ ...style, objectFit: 'contain' }} />
);

export const SpydraNode: NodeDefinition = {
    type: 'automation-spydra', category: 'industry', label: 'Spydra',
    description: 'Create and track tokenized assets, ownership transfers and approvals',
    Icon: SpydraIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={SpydraIcon} iconColor="" />),
};
