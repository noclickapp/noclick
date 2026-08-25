// Salesforce REST API automation node definition.
// Provides workflow integration with Salesforce for queries, records, batch operations, and metadata.

import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

// Create icon component from SVG file
const SalesforceIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img
            ref={ref}
            src="/icons/salesforce.svg"
            alt=""
            className={className}
            style={style}
            {...props}
        />
    )
);
SalesforceIcon.displayName = 'SalesforceIcon';

const SalesforceNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={SalesforceIcon} iconColor="" />;
};

export const SalesforceNode: NodeDefinition = {
    type: 'automation-salesforce',
    label: 'Salesforce',
    description: 'Salesforce CRM Ops',
    Icon: SalesforceIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(SalesforceNodeComponent),
};
