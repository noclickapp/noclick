// Defines Context Dev in the workflow palette and integration catalog.
// The schema generated from the backend supplies its operation and credential forms.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const ContextDevIcon = ({
    className,
    style,
}: {
    className?: string;
    style?: CSSProperties;
}) => (
    <img
        src="/icons/context-dev.png"
        alt=""
        aria-hidden="true"
        className={className}
        style={{ ...style, objectFit: 'contain' }}
    />
);

export const ContextDevNode: NodeDefinition = {
    type: 'automation-context-dev',
    category: 'content-research',
    label: 'Context Dev',
    description:
        'Research the web, enrich people and brands, and monitor website changes',
    keywords: [
        'context.dev',
        'scrape',
        'crawl',
        'web search',
        'news',
        'website monitoring',
    ],
    Icon: ContextDevIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => (
        <AutomationNode {...props} Icon={ContextDevIcon} iconColor="" />
    )),
};
