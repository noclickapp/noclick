import type { CSSProperties as BrandCSSProperties } from 'react';
// Recurly subscription billing node definition for the workflow canvas.
// The icon uses the official Recurly mark cropped from its site wordmark.

import { forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';

// Sourced brand artwork: https://logos.composio.dev/api/recurly
const PreferredBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <img src="/icons/recurly-preferred-brand.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as BrandCSSProperties} />
);

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
    Icon: PreferredBrandIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: (props: NodeProps) => <AutomationNode {...props} Icon={PreferredBrandIcon} iconColor="" />,
};
