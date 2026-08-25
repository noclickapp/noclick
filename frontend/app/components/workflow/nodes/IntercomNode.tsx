// Intercom customer messaging automation node definition.
// Provides workflow integration with the Intercom REST API (contacts,
// conversations, tickets, companies, messaging) plus a webhook trigger.

import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const IntercomIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <img
        ref={ref}
        src="/icons/intercom.svg"
        alt=""
        // NOT brand-mono: intercom's mark is light CYAN (#6AFDEF), not white —
        // inverting flips it to dark red. Keep its brand color.
        className={className || ''}
        style={style}
        {...props}
    />
));
IntercomIcon.displayName = 'IntercomIcon';

const IntercomNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={IntercomIcon} iconColor="" />;
};

export const IntercomNode: NodeDefinition = {
    type: 'automation-intercom',
    label: 'Intercom',
    description: 'Intercom customer messaging automation',
    Icon: IntercomIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(IntercomNodeComponent),
};
