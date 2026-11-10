import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
import {
    NodeDefinition,
    SvgIconComponent,
} from '~/components/workflow/nodes/types';

const CoinMarketCapIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <ThemedBrandImg light="/icons/coinmarketcap.svg" dark="/icons/coinmarketcap-dark.svg" className={className} style={style} {...props} ref={ref} />
));
CoinMarketCapIcon.displayName = 'CoinMarketCapIcon';

// Exact publisher asset; provenance is recorded beside the SVG.
export const CoinMarketCapNode: NodeDefinition = {
    type: 'automation-coinmarketcap',
    label: 'CoinMarketCap',
    description: 'Cryptocurrency prices, market data, exchanges and sentiment',
    category: 'finance-accounting',
    Icon: CoinMarketCapIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo(function CoinMarketCapComponent(props: NodeProps) {
        return (
            <AutomationNode {...props} Icon={CoinMarketCapIcon} iconColor="" />
        );
    }),
};
