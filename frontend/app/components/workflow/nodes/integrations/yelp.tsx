import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const YelpIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/yelp.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const YelpNode: NodeDefinition = {
    type: 'automation-yelp', category: 'content-research', label: 'Yelp',
    description: 'Find businesses, reviews, events and categories, and create Yelp AI conversations',
    Icon: YelpIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={YelpIcon} iconColor="" />),
};
