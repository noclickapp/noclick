import type { CSSProperties as BrandCSSProperties } from 'react';
import { memo } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition } from '~/components/workflow/nodes/types';

// Sourced brand artwork: https://logos.composio.dev/api/todoist
const PreferredBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <img src="/icons/todoist-preferred-brand.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as BrandCSSProperties} />
);

const TodoistNodeComponent = (props: NodeProps) => (
    <AutomationNode {...props} Icon={PreferredBrandIcon} iconColor="text-red-500" />
);

export const TodoistNode: NodeDefinition = {
    type: 'automation-todoist',
    label: 'Todoist',
    description: 'Plan and complete Todoist tasks, projects, sections, labels, and comments',
    category: 'productivity',
    Icon: PreferredBrandIcon,
    iconColor: 'text-red-500',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo(TodoistNodeComponent),
};
