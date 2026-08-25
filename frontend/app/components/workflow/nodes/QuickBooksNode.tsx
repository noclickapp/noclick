// QuickBooks Online (Intuit Accounting API) automation node definition.
// Provides workflow integration with QuickBooks Online (invoices, customers,
// vendors, bills, payments, items, accounts, reports) plus a webhook trigger
// for entity-change events.

import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const QuickBooksIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <img
        ref={ref}
        src="/icons/quickbooks.svg"
        alt=""
        className={className}
        style={style}
        {...props}
    />
));
QuickBooksIcon.displayName = 'QuickBooksIcon';

const QuickBooksNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={QuickBooksIcon} iconColor="" />;
};

export const QuickBooksNode: NodeDefinition = {
    type: 'automation-quickbooks',
    label: 'QuickBooks',
    description: 'QuickBooks Online accounting automation',
    Icon: QuickBooksIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(QuickBooksNodeComponent),
};
