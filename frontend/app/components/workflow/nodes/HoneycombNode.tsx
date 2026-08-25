// Honeycomb observability automation node definition.
// Provides workflow integration with the Honeycomb REST API (v1 + v2 Management):
// events, datasets/columns, boards, queries, markers, triggers, SLOs & burn
// alerts, recipients, and environments/API keys — plus native webhook triggers
// (via webhook Recipients) for when a Honeycomb trigger or burn alert fires.

import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const HoneycombIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <img
        ref={ref}
        src="/icons/honeycomb.svg"
        alt=""
        className={className}
        style={style}
        {...props}
    />
));
HoneycombIcon.displayName = 'HoneycombIcon';

const HoneycombNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={HoneycombIcon} iconColor="" />;
};

export const HoneycombNode: NodeDefinition = {
    type: 'automation-honeycomb',
    label: 'Honeycomb',
    description: 'Honeycomb observability automation',
    Icon: HoneycombIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(HoneycombNodeComponent),
};
