// Airtable REST API automation node definition.
// Provides workflow integration with Airtable for bases, records, comments, and webhooks.

import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

// Create icon component from SVG file
const AirtableIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img
            ref={ref}
            src="/icons/airtable.svg"
            alt=""
            className={className}
            style={style}
            {...props}
        />
    )
);
AirtableIcon.displayName = 'AirtableIcon';

const AirtableNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={AirtableIcon} iconColor="" />;
};

export const AirtableNode: NodeDefinition = {
    type: 'automation-airtable',
    label: 'Airtable',
    description: 'Airtable operations',
    Icon: AirtableIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(AirtableNodeComponent),
};
