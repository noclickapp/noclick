import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


const PolymarketUSIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/polymarket-us.png" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
PolymarketUSIcon.displayName = 'PolymarketUSIcon';

// Exact publisher asset; provenance is recorded beside the icon.
export const PolymarketUSNode: NodeDefinition = {
    type: 'automation-polymarket-us',
    label: 'Polymarket US',
    description: 'Markets, portfolio balances and signed order management',
    category: 'finance-accounting',
    Icon: PolymarketUSIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={PolymarketUSIcon} iconColor="" />),
};
