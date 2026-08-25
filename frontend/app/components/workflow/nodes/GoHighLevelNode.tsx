// GoHighLevel (LeadConnector) automation node definition.
// Provides workflow integration with the HighLevel REST API v2 (contacts,
// conversations, opportunities, calendars, invoices, payments, products, and
// more) via a Private Integration Token credential.

import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const GoHighLevelIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <img ref={ref} src="/icons/gohighlevel.svg" alt="" className={className} style={style} {...props} />
));
GoHighLevelIcon.displayName = 'GoHighLevelIcon';

const GoHighLevelNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={GoHighLevelIcon} iconColor="" />;
};

export const GoHighLevelNode: NodeDefinition = {
    type: 'automation-gohighlevel',
    label: 'GoHighLevel',
    description: 'GoHighLevel (LeadConnector) CRM automation',
    Icon: GoHighLevelIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(GoHighLevelNodeComponent),
};
