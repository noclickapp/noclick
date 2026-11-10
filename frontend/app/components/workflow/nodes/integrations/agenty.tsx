import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const AgentyIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/agenty.svg" dark="/icons/agenty-dark.svg" className={className} style={style} />
);

export const AgentyNode: NodeDefinition = {
    type: 'automation-agenty', category: 'content-research', label: 'Agenty',
    description: 'Run scraping jobs, retrieve results, and manage agent inputs, lists and schedules',
    keywords: ['scraping', 'web scraping', 'data extraction', 'crawler'],
    Icon: AgentyIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={AgentyIcon} iconColor="" />),
};
