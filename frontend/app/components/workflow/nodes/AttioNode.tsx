// Attio CRM automation node definition.
// Provides workflow integration with the Attio v2 API (records, lists, notes,
// tasks, comments) plus a webhook trigger for record/list-entry/note/task events.

import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const AttioIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <img
        ref={ref}
        src="/icons/attio.svg"
        alt=""
        className={`brand-mono ${className || ''}`}
        style={style}
        {...props}
    />
));
AttioIcon.displayName = 'AttioIcon';

const AttioNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={AttioIcon} iconColor="" />;
};

export const AttioNode: NodeDefinition = {
    type: 'automation-attio',
    label: 'Attio',
    description: 'Attio CRM automation',
    Icon: AttioIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(AttioNodeComponent),
};
