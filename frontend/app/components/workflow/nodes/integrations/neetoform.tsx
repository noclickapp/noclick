// NeetoForm's workspace integration for forms, responses and webhook callbacks.
// Schema-generated controls share the standard automation node renderer.
import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const NeetoformIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/neetoform.svg" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
NeetoformIcon.displayName = 'NeetoformIcon';

export const NeetoformNode: NodeDefinition = {
    type: 'automation-neetoform',
    label: 'NeetoForm',
    description: 'Manage workspace forms, submissions, questions, insights and webhooks',
    category: 'forms',
    keywords: ['neetoform', 'forms', 'surveys', 'responses', 'submissions'],
    Icon: NeetoformIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={NeetoformIcon} iconColor="" />),
};
