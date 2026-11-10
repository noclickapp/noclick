import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const BeachDayApiIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/beach-day-api.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const BeachDayApiNode: NodeDefinition = {
    type: 'automation-beach-day-api', category: 'industry', label: 'Beach Day API',
    description: 'Read beaches, conditions, scores, rules, amenities, tides and countries',
    Icon: BeachDayApiIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={BeachDayApiIcon} iconColor="" />),
};
