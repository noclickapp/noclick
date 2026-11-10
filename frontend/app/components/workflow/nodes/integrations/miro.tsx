import type { CSSProperties as BrandCSSProperties } from 'react';
import { memo } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition } from '~/components/workflow/nodes/types';

// Sourced brand artwork: https://logos.composio.dev/api/miro
const PreferredBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <img src="/icons/miro-preferred-brand.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const MiroNode: NodeDefinition = {
    type: 'automation-miro',
    label: 'Miro',
    description: 'Watch board activity and manage boards, sticky notes, cards, text and tags',
    category: 'productivity',
    Icon: PreferredBrandIcon,
    iconColor: 'text-yellow-400',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => (
        <AutomationNode {...props} Icon={PreferredBrandIcon} iconColor="text-yellow-400" />
    )),
};
