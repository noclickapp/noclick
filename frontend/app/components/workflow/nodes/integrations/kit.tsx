import { memo } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition } from '~/components/workflow/nodes/types';


import type { CSSProperties as BrandCSSProperties } from 'react';
// Vector brand artwork from https://kit.com/brand

const PreferredBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <img src="/icons/kit-brand-vector.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as BrandCSSProperties} />
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
