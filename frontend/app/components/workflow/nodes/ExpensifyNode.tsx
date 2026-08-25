// Expensify expense-management automation node definition.
// Provides workflow integration with the Expensify Integration Server API
// (exports, report/expense/policy creation, policy reads, and updates).

import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const ExpensifyIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <img
        ref={ref}
        src="/icons/expensify.svg"
        alt=""
        className={className}
        style={style}
        {...props}
    />
));
ExpensifyIcon.displayName = 'ExpensifyIcon';

const ExpensifyNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={ExpensifyIcon} iconColor="" />;
};

export const ExpensifyNode: NodeDefinition = {
    type: 'automation-expensify',
    label: 'Expensify',
    description: 'Expensify expense-management automation',
    Icon: ExpensifyIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(ExpensifyNodeComponent),
};
