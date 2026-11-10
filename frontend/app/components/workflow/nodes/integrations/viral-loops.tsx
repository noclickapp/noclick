import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const ViralLoopsIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => <img ref={ref} src="/icons/viral-loops.svg" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />,
);
ViralLoopsIcon.displayName = 'ViralLoopsIcon';

export const ViralLoopsNode: NodeDefinition = {
    type: 'automation-viral-loops',
    label: 'Viral Loops',
    category: 'marketing',
    description: 'Campaign stats, participants, referrals, conversions and rewards',
    keywords: ['referral', 'waitlist', 'giveaway', 'viral marketing'],
    Icon: ViralLoopsIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={ViralLoopsIcon} iconColor="" />),
};
