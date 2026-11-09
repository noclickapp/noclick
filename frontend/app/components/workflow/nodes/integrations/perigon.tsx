import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


const PerigonIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/perigon.png" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
PerigonIcon.displayName = 'PerigonIcon';

// Exact publisher asset; provenance is recorded beside the icon.
export const PerigonNode: NodeDefinition = {
    type: 'automation-perigon',
    label: 'Perigon',
    description: 'Search news intelligence and manage source groups and watchlists',
    category: 'content-research',
    Icon: PerigonIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={PerigonIcon} iconColor="" />),
};
