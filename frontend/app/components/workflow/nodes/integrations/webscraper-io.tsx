import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const WebscraperIoIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/webscraper-io.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' } as CSSProperties} />
);

export const WebscraperIoNode: NodeDefinition = {
    type: 'automation-webscraper-io', category: 'content-research', label: 'Webscraper Io',
    description: 'Manage cloud sitemaps, scraping jobs, schedules, tags, and data exports',
    keywords: ['web scraper', 'webscraper.io', 'web scraping', 'crawler'],
    Icon: WebscraperIoIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={WebscraperIoIcon} iconColor="" />),
};
