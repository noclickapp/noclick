import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const AssemblyComIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/assemblycom.png" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
AssemblyComIcon.displayName = 'AssemblyComIcon';

export const AssemblyComNode: NodeDefinition = {
    type: 'automation-assemblycom',
    label: 'Assembly.com',
    description: 'Manage portal clients, companies, tasks, notes and messages',
    category: 'crm-sales',
    keywords: ['Assembly', 'Copilot', 'client portal'],
    Icon: AssemblyComIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={AssemblyComIcon} iconColor="" />),
};
