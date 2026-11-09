// Adds PromptLayer to the workflow palette and integration catalog.
// The official publisher logo identifies prompt releases, feedback and evaluation operations.
import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const PromptLayerIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/promptlayer.svg" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
PromptLayerIcon.displayName = 'PromptLayerIcon';

export const PromptLayerNode: NodeDefinition = {
    type: 'automation-promptlayer',
    label: 'PromptLayer',
    description: 'Manage prompt versions and releases, request feedback, tables and evaluations',
    category: 'ai',
    keywords: ['promptlayer', 'prompts', 'LLM', 'evaluations', 'prompt registry'],
    Icon: PromptLayerIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={PromptLayerIcon} iconColor="" />),
};
