// Klaviyo (email/SMS marketing) automation node definition.
// Covers profiles, lists, segments, events, metrics, campaigns, flows,
// templates, catalogs, coupons, tags, images, webhooks, and an on-event push
// trigger. Authenticated with a private API key or OAuth.

import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const KlaviyoIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <img ref={ref} src="/icons/klaviyo.svg" alt="" className={className} style={style} {...props} />
));
KlaviyoIcon.displayName = 'KlaviyoIcon';

const KlaviyoNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={KlaviyoIcon} iconColor="" />;
};

export const KlaviyoNode: NodeDefinition = {
    type: 'automation-klaviyo',
    label: 'Klaviyo',
    description: 'Klaviyo email & SMS marketing automation',
    Icon: KlaviyoIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(KlaviyoNodeComponent),
};
