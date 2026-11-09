import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


const BitwardenIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/bitwarden.svg" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
BitwardenIcon.displayName = 'BitwardenIcon';

// Exact publisher asset; provenance is recorded beside the SVG.
export const BitwardenNode: NodeDefinition = {
    type: 'automation-bitwarden',
    label: 'Bitwarden',
    description: 'Start workflows from organization events and manage members, groups, collections and policies',
    category: 'developer-tools',
    Icon: BitwardenIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={BitwardenIcon} iconColor="" />),
};
