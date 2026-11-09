// Defines Twelve Data in the canvas and integration catalog.
// The official provider icon is reviewed in its provenance sidecar.
import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const TwelveDataIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/twelve-data.png" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
TwelveDataIcon.displayName = 'TwelveDataIcon';

export const TwelveDataNode: NodeDefinition = {
    type: 'automation-twelve-data',
    label: 'Twelve Data',
    description: 'Market prices, time series, currencies, financials and technical indicators',
    category: 'finance-accounting',
    keywords: ['twelvedata', 'stocks', 'forex', 'crypto', 'market data', 'financial data'],
    Icon: TwelveDataIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={TwelveDataIcon} iconColor="" />),
};
