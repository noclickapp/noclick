// Apollo.io automation node definition.
// Provides workflow integration with Apollo.io for CRM, enrichment, and sales automation.

import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

// Create icon component from SVG file
const ApolloIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img
            ref={ref}
            src="/icons/apollo.svg"
            alt=""
            className={className}
            style={style}
            {...props}
        />
    )
);
ApolloIcon.displayName = 'ApolloIcon';

const ApolloNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={ApolloIcon} iconColor="" />;
};

export const ApolloNode: NodeDefinition = {
    type: 'automation-apollo',
    label: 'Apollo',
    description: 'Apollo automation',
    Icon: ApolloIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(ApolloNodeComponent),
};
