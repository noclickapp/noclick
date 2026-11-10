import { memo } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition } from '~/components/workflow/nodes/types';


import type { CSSProperties as BrandCSSProperties } from 'react';
import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
// Vector brand artwork from https://kit.com/brand

const PreferredBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <ThemedBrandImg light="/icons/kit-brand-vector.svg" className={className} style={style} />
);

export const KitNode: NodeDefinition = {
    type: 'automation-kit',
    label: 'Kit',
    description: 'Manage subscribers, tags, forms, sequences, broadcasts and webhooks',
    category: 'marketing',
    Icon: PreferredBrandIcon,
    iconColor: 'text-violet-500',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => (
        <AutomationNode {...props} Icon={PreferredBrandIcon} iconColor="text-violet-500" />
    )),
};
