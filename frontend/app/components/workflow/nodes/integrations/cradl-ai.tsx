// Registers Cradl AI in the integration catalog and workflow canvas.
// The icon is the provider's published documentation favicon, reviewed beside the asset.
import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const CradlAIIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/cradl-ai.png" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
CradlAIIcon.displayName = 'CradlAIIcon';

export const CradlAINode: NodeDefinition = {
    type: 'automation-cradl-ai',
    label: 'Cradl AI',
    description: 'Automate document extraction, agent runs and human review tasks',
    category: 'ai',
    keywords: ['Cradl', 'OCR', 'document extraction', 'invoice', 'human review'],
    Icon: CradlAIIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={CradlAIIcon} iconColor="" />),
};
