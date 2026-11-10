import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const ScaleAiIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <ThemedBrandImg light="/icons/scale-ai.svg" dark="/icons/scale-ai-dark.svg" className={className} style={style} {...props} ref={ref} />
    ),
);
ScaleAiIcon.displayName = 'ScaleAiIcon';

export const ScaleAiNode: NodeDefinition = {
    type: 'automation-scale-ai',
    label: 'Scale AI',
    description: 'Deploy models, run inference, manage fine-tuning jobs and files with Scale Launch',
    category: 'ai',
    keywords: ['Scale Ai', 'Scale Launch', 'machine learning', 'model endpoints', 'fine tuning'],
    Icon: ScaleAiIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={ScaleAiIcon} iconColor="" />),
};
