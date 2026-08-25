// Freshsales (Freshworks CRM) automation node definition.
// Provides workflow integration with the Freshsales CRM REST API (contacts,
// accounts, deals, tasks, activities, search) plus a webhook trigger for
// outbound events fired by a Freshsales Workflow.

import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const FreshsalesIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <img
        ref={ref}
        src="/icons/freshsales.svg"
        alt=""
        className={className}
        style={style}
        {...props}
    />
));
FreshsalesIcon.displayName = 'FreshsalesIcon';

const FreshsalesNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={FreshsalesIcon} iconColor="" />;
};

export const FreshsalesNode: NodeDefinition = {
    type: 'automation-freshsales',
    label: 'Freshsales',
    description: 'Freshsales CRM automation',
    Icon: FreshsalesIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(FreshsalesNodeComponent),
};
