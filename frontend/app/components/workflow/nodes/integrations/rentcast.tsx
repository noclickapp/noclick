import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const RentCastIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/rentcast.svg" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
RentCastIcon.displayName = 'RentCastIcon';

export const RentCastNode: NodeDefinition = {
    type: 'automation-rentcast',
    label: 'RentCast',
    description: 'US property records, value and rent estimates, listings and market statistics',
    category: 'industry',
    keywords: ['real estate', 'property', 'rental', 'valuation', 'comparables'],
    Icon: RentCastIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={RentCastIcon} iconColor="" />),
};
