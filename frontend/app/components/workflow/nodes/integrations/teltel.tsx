import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


const TeltelIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/teltel.svg" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
TeltelIcon.displayName = 'TeltelIcon';

// Exact publisher asset; provenance is recorded beside the SVG.
export const TeltelNode: NodeDefinition = {
    type: 'automation-teltel',
    label: 'Teltel',
    description: 'Contacts, groups, SMS, call history and account data',
    category: 'communication',
    Icon: TeltelIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={TeltelIcon} iconColor="" />),
};
