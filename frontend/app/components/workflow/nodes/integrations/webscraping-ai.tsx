import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


const WebscrapingAiIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/webscraping-ai.png" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
WebscrapingAiIcon.displayName = 'WebscrapingAiIcon';

// Official publisher asset; provenance is recorded beside the image.
export const WebscrapingAiNode: NodeDefinition = {
    type: 'automation-webscraping-ai',
    label: 'WebScraping.AI',
    description: 'Scrape HTML and Markdown, extract fields with AI, search Google and read account credits',
    category: 'content-research',
    Icon: WebscrapingAiIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={WebscrapingAiIcon} iconColor="" />),
};
