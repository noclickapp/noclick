// PhantomBuster web scraping & automation node definition.
// Provides workflow integration with the PhantomBuster v2 API (agents/Phantoms,
// containers, scripts, org storage, AI utilities) plus a webhook trigger for
// per-Phantom completion notifications.

import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const PhantomBusterIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <img
        ref={ref}
        src="/icons/phantombuster.svg"
        alt=""
        className={className}
        style={style}
        {...props}
    />
));
PhantomBusterIcon.displayName = 'PhantomBusterIcon';

const PhantomBusterNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={PhantomBusterIcon} iconColor="" />;
};

export const PhantomBusterNode: NodeDefinition = {
    type: 'automation-phantombuster',
    label: 'PhantomBuster',
    description: 'PhantomBuster web scraping & automation',
    Icon: PhantomBusterIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(PhantomBusterNodeComponent),
};
