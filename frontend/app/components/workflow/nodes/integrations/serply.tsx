// Exposes Serply search operations in the workflow and integration catalogs.
// The official provider icon identifies the API key connection and search tools.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const SerplyIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/serply.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const SerplyNode: NodeDefinition = {
    type: 'automation-serply', category: 'content-research', label: 'Serply',
    description: 'Search Google, Bing, news, images, videos, jobs, research and products; check SERP rankings and crawl results.',
    keywords: ['search', 'serp', 'seo', 'research', 'google', 'bing'],
    Icon: SerplyIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={SerplyIcon} iconColor="" />),
};
