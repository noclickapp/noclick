// Devin AI software engineer automation node definition.
// Provides workflow integration with the Devin v1 API (sessions, attachments,
// knowledge, playbooks, secrets) plus an account "get self" call.

import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const DevinIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <img ref={ref} src="/icons/devin.svg" alt="" className={className} style={style} {...props} />
));
DevinIcon.displayName = 'DevinIcon';

const DevinNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={DevinIcon} iconColor="" />;
};

export const DevinNode: NodeDefinition = {
    type: 'automation-devin',
    label: 'Devin',
    description: 'Devin AI software engineer automation',
    Icon: DevinIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(DevinNodeComponent),
};
