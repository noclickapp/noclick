// Zendesk Support automation node definition.
// Provides workflow integration with the Zendesk Support v2 API (tickets, users,
// organizations, search, metadata) plus a webhook trigger for ticket events.

import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const ZendeskIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <img
        ref={ref}
        src="/icons/zendesk.svg"
        alt=""
        className={`brand-mono ${className || ''}`}
        style={style}
        {...props}
    />
));
ZendeskIcon.displayName = 'ZendeskIcon';

const ZendeskNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={ZendeskIcon} iconColor="" />;
};

export const ZendeskNode: NodeDefinition = {
    type: 'automation-zendesk',
    label: 'Zendesk',
    description: 'Zendesk Support automation',
    Icon: ZendeskIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(ZendeskNodeComponent),
};
