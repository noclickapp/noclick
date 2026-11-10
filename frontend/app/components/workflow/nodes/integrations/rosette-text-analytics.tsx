import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const RosetteTextAnalyticsIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <ThemedBrandImg light="/icons/rosette-text-analytics.svg" dark="/icons/rosette-text-analytics-dark.svg" className={className} style={style} {...props} ref={ref} />
    ),
);
RosetteTextAnalyticsIcon.displayName = 'RosetteTextAnalyticsIcon';

export const RosetteTextAnalyticsNode: NodeDefinition = {
    type: 'automation-rosette-text-analytics',
    label: 'Rosette Text Analytics',
    description: 'Analyze text, entities, sentiment, topics, names and semantic embeddings',
    category: 'ai',
    keywords: ['Babel Street', 'NLP', 'language', 'entities', 'sentiment'],
    Icon: RosetteTextAnalyticsIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={RosetteTextAnalyticsIcon} iconColor="" />),
};
