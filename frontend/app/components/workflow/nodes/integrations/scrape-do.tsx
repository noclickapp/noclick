import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const ScrapeDoIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/scrape-do.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const ScrapeDoNode: NodeDefinition = {
    type: 'automation-scrape-do', category: 'content-research', label: 'Scrape Do',
    description: 'Create and cancel asynchronous scraping jobs, retrieve results and monitor account credits',
    keywords: ['scrape.do', 'scrape_do', 'web scraping', 'async', 'crawler'],
    Icon: ScrapeDoIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={ScrapeDoIcon} iconColor="" />),
};
