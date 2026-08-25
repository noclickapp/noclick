// Perplexity AI automation node definition.
// Provides workflow integration with the Perplexity API (search-grounded chat
// completions, web search, agent responses, embeddings, models).

import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const PerplexityIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <img
        ref={ref}
        src="/icons/perplexity.svg"
        alt=""
        className={className}
        style={style}
        {...props}
    />
));
PerplexityIcon.displayName = 'PerplexityIcon';

const PerplexityNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={PerplexityIcon} iconColor="" />;
};

export const PerplexityNode: NodeDefinition = {
    type: 'automation-perplexity',
    label: 'Perplexity',
    description: 'Perplexity AI search-grounded chat, search, and embeddings',
    Icon: PerplexityIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(PerplexityNodeComponent),
};
