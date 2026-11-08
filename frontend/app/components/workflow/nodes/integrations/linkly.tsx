import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import {
    NodeDefinition,
    SvgIconComponent,
} from '~/components/workflow/nodes/types';

const LinklyIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <img
        ref={ref}
        src="/icons/linkly.png"
        alt=""
        className={className}
        style={{ ...style, objectFit: 'contain' }}
        {...props}
    />
));
LinklyIcon.displayName = 'LinklyIcon';

// Exact publisher asset; provenance is recorded beside the icon.
export const LinklyNode: NodeDefinition = {
    type: 'automation-linkly',
    label: 'Linkly',
    description:
        'Manage short links, domains, click analytics, conversions and webhooks',
    Icon: LinklyIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo(function LinklyComponent(props: NodeProps) {
        return <AutomationNode {...props} Icon={LinklyIcon} iconColor="" />;
    }),
};
