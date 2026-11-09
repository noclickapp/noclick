import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const ScrapegraphAIIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/scrapegraph-ai.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' } as CSSProperties} />
);

export const ScrapegraphAINode: NodeDefinition = {
    type: 'automation-scrapegraph-ai', category: 'content-research', label: 'Scrapegraph Ai',
    description: 'Scrape pages, extract JSON, search the web, manage monitors and crawls',
    keywords: ['ScrapeGraphAI', 'web scraping', 'extraction', 'website monitoring'],
    Icon: ScrapegraphAIIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={ScrapegraphAIIcon} iconColor="" />),
};
