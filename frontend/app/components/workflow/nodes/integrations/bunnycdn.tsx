// Bunny.net CDN, Shield, Stream, and Edge Script automation node.

import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const BunnyIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <img
        ref={ref}
        src="/icons/bunnycdn.svg"
        alt=""
        className={className}
        style={style}
        {...props}
    />
));
BunnyIcon.displayName = 'BunnyIcon';

const BunnyCDNNodeComponent = (props: NodeProps) => (
    <AutomationNode {...props} Icon={BunnyIcon} iconColor="" />
);

export const BunnyCDNNode: NodeDefinition = {
    type: 'automation-bunnycdn',
    label: 'Bunny.net',
    description: 'CDN, DNS, Shield, Stream, and edge automation',
    category: 'cloud-hosting',
    Icon: BunnyIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(BunnyCDNNodeComponent),
};
