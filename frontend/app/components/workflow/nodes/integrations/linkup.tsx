import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const LinkupIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/linkup.png" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
LinkupIcon.displayName = 'LinkupIcon';

export const LinkupNode: NodeDefinition = {
    type: 'automation-linkup',
    label: 'Linkup',
    description: 'Web search, page content, structured extraction and research',
    keywords: ['web search', 'research', 'scraping', 'AI', 'Linkup'],
    category: 'content-research',
    Icon: LinkupIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={LinkupIcon} iconColor="" />),
};
