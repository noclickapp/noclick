// Recurly subscription billing node definition for the workflow canvas.
// The icon uses the official Recurly mark cropped from its site wordmark.

import { forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';

const RecurlyIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>(({ className, ...props }, ref) => (
    <img ref={ref} src="/icons/recurly.svg" alt="" className={`brand-mono ${className ?? ''}`} {...props} />
));
RecurlyIcon.displayName = 'RecurlyIcon';

export const RecurlyNode: NodeDefinition = {
    type: 'automation-recurly',
    label: 'Recurly',
    description: 'Manage subscription billing in Recurly',
    Icon: RecurlyIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: (props: NodeProps) => <AutomationNode {...props} Icon={RecurlyIcon} iconColor="" />,
};
