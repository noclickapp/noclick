// Search1API catalog and canvas definition. The schema supplies its operation forms
// while this definition places the service in Content & Research.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const Search1ApiIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/search1api.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const Search1ApiNode: NodeDefinition = {
    type: 'automation-search1api', category: 'content-research', label: 'Search1API',
    description: 'Search the web and news, extract content, monitor usage and crawl sites',
    Icon: Search1ApiIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={Search1ApiIcon} iconColor="" />),
};
