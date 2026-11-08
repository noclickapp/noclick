import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const AgentyIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/agenty.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const AgentyNode: NodeDefinition = {
    type: 'automation-agenty', category: 'content-research', label: 'Agenty',
    description: 'Run scraping jobs, retrieve results, and manage agent inputs, lists and schedules',
    keywords: ['scraping', 'web scraping', 'data extraction', 'crawler'],
    Icon: AgentyIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={AgentyIcon} iconColor="" />),
};
