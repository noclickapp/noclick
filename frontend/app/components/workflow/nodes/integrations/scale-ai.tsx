import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const ScaleAiIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <>
            <img ref={ref} src="/icons/scale-ai.svg" alt="" className={`${className ?? ''} dark:hidden`} style={{ ...style, objectFit: 'contain' }} {...props} />
            <img src="/icons/scale-ai-dark.svg" alt="" className={`${className ?? ''} hidden dark:block`} style={{ ...style, objectFit: 'contain' }} {...props} />
        </>
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
