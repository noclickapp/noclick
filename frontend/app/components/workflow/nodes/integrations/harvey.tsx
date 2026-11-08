import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const HarveyIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/harvey.svg" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
HarveyIcon.displayName = 'HarveyIcon';

export const HarveyNode: NodeDefinition = {
    type: 'automation-harvey',
    label: 'Harvey',
    description: 'Manage legal Vault projects, search documents, sync clients and matters, and track Intake requests.',
    category: 'ai',
    Icon: HarveyIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={HarveyIcon} iconColor="" />),
};
