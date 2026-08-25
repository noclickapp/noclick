// Firecrawl web scraping & crawling automation node definition.
// Provides workflow integration with the Firecrawl v2 API (scrape, crawl, map,
// search, extract, agent, browser sessions) plus a webhook trigger for async
// job events.

import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const FirecrawlIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <img ref={ref} src="/icons/firecrawl.svg" alt="" className={className} style={style} {...props} />
));
FirecrawlIcon.displayName = 'FirecrawlIcon';

const FirecrawlNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={FirecrawlIcon} iconColor="" />;
};

export const FirecrawlNode: NodeDefinition = {
    type: 'automation-firecrawl',
    label: 'Firecrawl',
    description: 'Web scraping, crawling & extraction automation',
    Icon: FirecrawlIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(FirecrawlNodeComponent),
};
