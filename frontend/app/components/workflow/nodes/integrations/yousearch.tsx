import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const YousearchIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/yousearch.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const YousearchNode: NodeDefinition = {
    type: 'automation-yousearch', category: 'content-research', label: 'Yousearch',
    keywords: ['You.com', 'You Search', 'web search', 'research'],
    description: 'Search web and news with snippets, highlights and full-page content',
    Icon: YousearchIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={YousearchIcon} iconColor="" />),
};
