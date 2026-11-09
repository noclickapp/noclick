// Discover the Relevance AI node in the canvas and integration catalog.
// Use the official provider icon and place the integration in the AI section.
import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const RelevanceAIIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/relevance-ai.png" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
RelevanceAIIcon.displayName = 'RelevanceAIIcon';

export const RelevanceAINode: NodeDefinition = {
    type: 'automation-relevance-ai',
    label: 'Relevance AI',
    description: 'Run tools and agents, poll tool jobs, and manage project knowledge. Provider support covers agent and tool triggering; other published endpoints are currently unsupported.',
    category: 'ai',
    keywords: ['AI agents', 'tools', 'knowledge', 'RAG'],
    Icon: RelevanceAIIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={RelevanceAIIcon} iconColor="" />),
};
