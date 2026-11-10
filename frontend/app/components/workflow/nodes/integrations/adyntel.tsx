import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const AdyntelIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/adyntel.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const AdyntelNode: NodeDefinition = {
    type: 'automation-adyntel', category: 'marketing', label: 'Adyntel',
    description: 'Search Meta, Google, LinkedIn and TikTok ads and analyze domain keywords',
    keywords: ['ad intelligence', 'competitor research', 'ad library', 'Google Shopping'],
    Icon: AdyntelIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={AdyntelIcon} iconColor="" />),
};
