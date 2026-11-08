// Productboard feedback and roadmap automation node.

import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const ProductboardIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <img
        ref={ref}
        src="/icons/productboard.svg"
        alt=""
        className={className}
        style={style}
        {...props}
    />
));
ProductboardIcon.displayName = 'ProductboardIcon';

const ProductboardNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={ProductboardIcon} iconColor="" />;
};

export const ProductboardNode: NodeDefinition = {
    type: 'automation-productboard',
    label: 'Productboard',
    description: 'Feedback, features, teams, and roadmap automation',
    Icon: ProductboardIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(ProductboardNodeComponent),
};
