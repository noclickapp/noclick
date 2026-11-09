// Registers Wayfront in the canvas and integration catalog. The schema supplies
// its operations and manual connection fields through automatic discovery.
import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import {
    NodeDefinition,
    SvgIconComponent,
} from '~/components/workflow/nodes/types';

const WayfrontIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <img
        ref={ref}
        src="/icons/wayfront.svg"
        alt=""
        className={className}
        style={{ ...style, objectFit: 'contain' }}
        {...props}
    />
));
WayfrontIcon.displayName = 'WayfrontIcon';

// Exact publisher asset; provenance is recorded beside the SVG.
export const WayfrontNode: NodeDefinition = {
    type: 'automation-wayfront',
    label: 'Wayfront',
    description: 'Manage clients, companies, orders, tasks and messages',
    category: 'crm-sales',
    Icon: WayfrontIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => (
        <AutomationNode {...props} Icon={WayfrontIcon} iconColor="" />
    )),
};
