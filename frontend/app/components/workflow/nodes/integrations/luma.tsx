// Luma (lu.ma) event-management automation node definition.
// Provides workflow integration with the Luma public API (events, guests, hosts,
// ticket types, coupons, calendar, contacts, webhooks) plus a webhook trigger
// for Luma event/guest/ticket changes.

import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


import type { CSSProperties as BrandCSSProperties } from 'react';
// Vector brand artwork from https://luma.com

// Sourced brand artwork: https://github.com/ComposioHQ/logo-cdn/blob/3eff86db0d0ac01806c4a8791a6965c35ea23ffb/src/assets/luma.svg
const PreferredBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <>
        <img src="/icons/luma-preferred-brand.svg" alt="" aria-hidden="true" className={`${className ?? ''} dark:hidden`}
            style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as BrandCSSProperties} />
        <img src="/icons/luma-preferred-brand-dark.svg" alt="" aria-hidden="true" className={`${className ?? ''} hidden dark:block`}
            style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as BrandCSSProperties} />
    </>
);

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const LumaIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <img ref={ref} src="/icons/luma.svg" alt="" className={className} style={style} {...props} />
));
LumaIcon.displayName = 'LumaIcon';

const LumaNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={PreferredBrandIcon} iconColor="" />;
};

export const LumaNode: NodeDefinition = {
    type: 'automation-luma',
    label: 'Luma',
    description: 'Luma event management automation',
    Icon: PreferredBrandIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(LumaNodeComponent),
};
