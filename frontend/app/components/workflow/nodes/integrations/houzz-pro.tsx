import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


const HouzzProIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/houzz-pro.svg" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
HouzzProIcon.displayName = 'HouzzProIcon';

// Exact publisher asset; provenance is recorded beside the SVG.
export const HouzzProNode: NodeDefinition = {
    type: 'automation-houzz-pro',
    label: 'Houzz Pro',
    description: 'Manage Houzz Pro projects, leads, contacts, tasks and notes',
    category: 'industry',
    Icon: HouzzProIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={HouzzProIcon} iconColor="" />),
};
