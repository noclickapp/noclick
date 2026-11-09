import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const DovetailIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/dovetail.svg" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
DovetailIcon.displayName = 'DovetailIcon';

export const DovetailNode: NodeDefinition = {
    type: 'automation-dovetail',
    label: 'Dovetail',
    description: 'Research projects, data, docs, contacts and tags',
    category: 'content-research',
    Icon: DovetailIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={DovetailIcon} iconColor="" />),
};
