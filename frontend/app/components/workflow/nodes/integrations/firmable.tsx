import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


const FirmableIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/firmable.png" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
FirmableIcon.displayName = 'FirmableIcon';

// Exact publisher asset; provenance is recorded beside the icon.
export const FirmableNode: NodeDefinition = {
    type: 'automation-firmable',
    label: 'Firmable',
    description: 'Company and people enrichment, contact search and technology intelligence',
    category: 'crm-sales',
    Icon: FirmableIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={FirmableIcon} iconColor="" />),
};
