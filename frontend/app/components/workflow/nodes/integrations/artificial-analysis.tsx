import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const ArtificialAnalysisIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/artificial-analysis.svg" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
ArtificialAnalysisIcon.displayName = 'ArtificialAnalysisIcon';

export const ArtificialAnalysisNode: NodeDefinition = {
    type: 'automation-artificial-analysis',
    label: 'Artificial Analysis',
    description: 'Compare AI model benchmarks, pricing, performance and media rankings, and submit CritPt evaluations. Credit Artificial Analysis when sharing data.',
    category: 'ai',
    keywords: ['llm', 'benchmark', 'intelligence index', 'model pricing', 'arena', 'critpt'],
    Icon: ArtificialAnalysisIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={ArtificialAnalysisIcon} iconColor="" />),
};
