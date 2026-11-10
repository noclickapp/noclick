import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


// Unmodified compact brand asset from https://www.netlify.com
import type { CSSProperties as BrandCSSProperties } from 'react';
const OfficialBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <img src="/icons/netlify-brand.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const NetlifyIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <img
        ref={ref}
        src="/icons/netlify.svg"
        alt=""
        className={className}
        style={style}
        {...props}
    />
));
NetlifyIcon.displayName = 'NetlifyIcon';

const NetlifyNodeComponent = (props: NodeProps) => (
    <AutomationNode {...props} Icon={OfficialBrandIcon} iconColor="" />
);

export const NetlifyNode: NodeDefinition = {
    type: 'automation-netlify',
    category: 'cloud-hosting',
    label: 'Netlify',
    description:
        'Manage sites, deploys, builds, forms, DNS, hooks, and environment variables',
    Icon: OfficialBrandIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(NetlifyNodeComponent),
};
