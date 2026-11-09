import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import {
    NodeDefinition,
    SvgIconComponent,
} from '~/components/workflow/nodes/types';

const PortalioIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <img
        ref={ref}
        src="/icons/portalio.svg"
        alt=""
        className={className}
        style={{ ...style, objectFit: 'contain' }}
        {...props}
    />
));
PortalioIcon.displayName = 'PortalioIcon';

// Exact publisher asset; provenance is recorded beside the SVG.
export const PortalioNode: NodeDefinition = {
    type: 'automation-portalio',
    label: 'Portal.io',
    description: 'Manage proposals, contacts, locations and catalog items',
    category: 'crm-sales',
    Icon: PortalioIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => (
        <AutomationNode {...props} Icon={PortalioIcon} iconColor="" />
    )),
};
