import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const BigOvenIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/bigoven.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain', '--brand-invert': 0 } as CSSProperties} />
);
export const BigOvenNode: NodeDefinition = {
    type: 'automation-bigoven', category: 'industry', label: 'BigOven',
    description: 'Search and manage recipes, grocery lists, notes and reviews',
    keywords: ['recipe', 'grocery', 'cooking', 'meal planning', '1,000,000+ Recipe and Grocery List API (v2)'],
    Icon: BigOvenIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={BigOvenIcon} iconColor="" />),
};
