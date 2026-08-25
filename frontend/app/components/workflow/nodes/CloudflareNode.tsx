// Cloudflare automation node definition.
// Provides workflow integration for Cloudflare APIs including DNS, Workers, KV,
// D1, R2, Pages, Stream, Images, WAF, Access, Tunnels, Queues, and Workers AI.

import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const CloudflareIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img
            ref={ref}
            src="/icons/cloudflare.svg"
            alt=""
            className={className}
            style={style}
            {...props}
        />
    )
);
CloudflareIcon.displayName = 'CloudflareIcon';

const CloudflareNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={CloudflareIcon} iconColor="" />;
};

export const CloudflareNode: NodeDefinition = {
    type: 'automation-cloudflare',
    label: 'Cloudflare',
    description: 'Cloudflare automation',
    Icon: CloudflareIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(CloudflareNodeComponent),
};
