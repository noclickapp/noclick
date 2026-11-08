import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


const DocsbotAiIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/docsbot-ai.png" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
DocsbotAiIcon.displayName = 'DocsbotAiIcon';

// Exact publisher asset; provenance is recorded beside the icon.
export const DocsbotAiNode: NodeDefinition = {
    type: 'automation-docsbot-ai',
    label: 'DocsBot AI',
    description: 'Chat, search, leads, conversations and deep research',
    Icon: DocsbotAiIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={DocsbotAiIcon} iconColor="" />),
};
