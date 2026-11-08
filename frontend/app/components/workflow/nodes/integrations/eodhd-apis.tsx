// Discovers EODHD APIs in the workflow canvas and finance integration catalog.
// Uses the official publisher icon to identify the financial data provider.
import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import {
    NodeDefinition,
    SvgIconComponent,
} from '~/components/workflow/nodes/types';

const EodhdApisIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <img
        ref={ref}
        src="/icons/eodhd-apis.png"
        alt=""
        className={className}
        style={{ ...style, objectFit: 'contain' }}
        {...props}
    />
));
EodhdApisIcon.displayName = 'EodhdApisIcon';

// Exact publisher asset; provenance is recorded beside the asset.
export const EodhdApisNode: NodeDefinition = {
    type: 'automation-eodhd-apis',
    label: 'EODHD APIs',
    description:
        'EODHD prices, fundamentals, financial news and market calendars',
    category: 'finance-accounting',
    Icon: EodhdApisIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo(function EodhdApisComponent(props: NodeProps) {
        return <AutomationNode {...props} Icon={EodhdApisIcon} iconColor="" />;
    }),
};
