import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


const JunglescoutIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/junglescout.png" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
JunglescoutIcon.displayName = 'JunglescoutIcon';

// Exact publisher asset; provenance is recorded beside the SVG.
export const JunglescoutNode: NodeDefinition = {
    type: 'automation-junglescout',
    label: 'Jungle Scout',
    description: 'Amazon product, keyword, sales and share of voice research',
    category: 'ecommerce',
    Icon: JunglescoutIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={JunglescoutIcon} iconColor="" />),
};
