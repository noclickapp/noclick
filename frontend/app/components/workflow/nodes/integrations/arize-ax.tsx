// Expose Arize AX in the canvas and integration catalog.
// The icon uses the publisher asset with provenance recorded beside it.
import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const ArizeAxIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/arize-ax.png" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
ArizeAxIcon.displayName = 'ArizeAxIcon';

export const ArizeAxNode: NodeDefinition = {
    type: 'automation-arize-ax',
    label: 'Arize AX',
    description: 'Manage AI datasets, experiment runs and versioned prompts',
    category: 'ai',
    keywords: ['Arize Ax', 'Arize AI', 'LLM', 'evaluation', 'experiments', 'observability', 'prompts'],
    Icon: ArizeAxIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={ArizeAxIcon} iconColor="" />),
};
