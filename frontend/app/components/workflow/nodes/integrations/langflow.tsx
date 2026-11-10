import { forwardRef, type ImgHTMLAttributes } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const LangflowIcon = forwardRef<HTMLImageElement, ImgHTMLAttributes<HTMLImageElement>>(
    ({ style, ...props }, ref) => (
        <img {...props} ref={ref} src="/icons/langflow.svg" alt="" aria-hidden="true"
            style={{ ...style, objectFit: 'contain' }} />
    ),
);
LangflowIcon.displayName = 'LangflowIcon';

export const LangflowNode: NodeDefinition = {
    type: 'automation-langflow',
    label: 'Langflow',
    description: 'Manage project, flow and file metadata without executing models.',
    category: 'ai',
    Icon: LangflowIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: (props: NodeProps) => <AutomationNode {...props} Icon={LangflowIcon} iconColor="" />,
};
