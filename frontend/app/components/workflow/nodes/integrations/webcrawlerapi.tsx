// Webcrawlerapi's catalog and canvas definition is discovered with its own node.
// The provider's official icon identifies crawling, extraction and feed workflows.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const WebcrawlerapiIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/webcrawlerapi.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const WebcrawlerapiNode: NodeDefinition = {
    type: 'automation-webcrawlerapi', category: 'content-research', label: 'Webcrawlerapi',
    description: 'Crawl websites, extract content, run agents and monitor website feeds',
    keywords: ['web crawler', 'scrape', 'markdown', 'website monitoring', 'RAG'],
    Icon: WebcrawlerapiIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={WebcrawlerapiIcon} iconColor="" />),
};
