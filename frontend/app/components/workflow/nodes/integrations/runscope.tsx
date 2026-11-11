import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const RunscopeIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/runscope.svg" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
RunscopeIcon.displayName = 'RunscopeIcon';

export const RunscopeNode: NodeDefinition = {
    type: 'automation-runscope',
    label: 'Runscope',
    description: 'Manage API tests, buckets, environments and completion notifications',
    category: 'monitoring',
    keywords: ['BlazeMeter', 'API monitoring', 'API testing'],
    Icon: RunscopeIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={RunscopeIcon} iconColor="" />),
};
