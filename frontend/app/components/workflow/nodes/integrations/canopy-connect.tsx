import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import {
    NodeDefinition,
    SvgIconComponent,
} from '~/components/workflow/nodes/types';

const CanopyConnectIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <img
        ref={ref}
        src="/icons/canopy-connect.png"
        alt=""
        className={className}
        style={{ ...style, objectFit: 'contain' }}
        {...props}
    />
));
CanopyConnectIcon.displayName = 'CanopyConnectIcon';

// Exact publisher asset; provenance is recorded beside the image.
export const CanopyConnectNode: NodeDefinition = {
    type: 'automation-canopy-connect',
    label: 'Canopy Connect',
    description: 'Insurance pulls, policy checks, monitoring and widgets',
    category: 'industry',
    Icon: CanopyConnectIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => (
        <AutomationNode {...props} Icon={CanopyConnectIcon} iconColor="" />
    )),
};
