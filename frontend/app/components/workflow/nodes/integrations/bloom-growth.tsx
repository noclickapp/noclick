import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const BloomGrowthIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <ThemedBrandImg light="/icons/bloom-growth.svg" dark="/icons/bloom-growth-dark.svg" className={className} style={style} {...props} ref={ref} />
    ),
);
BloomGrowthIcon.displayName = 'BloomGrowthIcon';

export const BloomGrowthNode: NodeDefinition = {
    type: 'automation-bloom-growth',
    label: 'Bloom Growth',
    description: 'Automate to-dos, goals, milestones, meeting issues and scorecards',
    category: 'productivity',
    keywords: ['rocks', 'weekly meeting', 'metrics', 'scorecard', 'traction tools'],
    Icon: BloomGrowthIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={BloomGrowthIcon} iconColor="" />),
};
