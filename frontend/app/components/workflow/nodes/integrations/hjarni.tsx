import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const HjarniIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/hjarni.svg" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
HjarniIcon.displayName = 'HjarniIcon';

export const HjarniNode: NodeDefinition = {
    type: 'automation-hjarni',
    label: 'Hjarni',
    description: 'Search and manage Markdown notes, folders and tags',
    category: 'productivity',
    keywords: ['knowledge base', 'markdown', 'notes', 'containers', 'tags'],
    Icon: HjarniIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={HjarniIcon} iconColor="" />),
};
