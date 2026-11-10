import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const BloomGrowthIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <>
            <img ref={ref} src="/icons/bloom-growth.svg" alt="" className={`${className ?? ''} dark:hidden`} style={{ ...style, objectFit: 'contain' }} {...props} />
            <img src="/icons/bloom-growth-dark.svg" alt="" className={`${className ?? ''} hidden dark:block`} style={{ ...style, objectFit: 'contain' }} {...props} />
        </>
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
