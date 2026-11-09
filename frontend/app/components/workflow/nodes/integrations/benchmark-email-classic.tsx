import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const BenchmarkEmailClassicIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/benchmark-email-classic.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const BenchmarkEmailClassicNode: NodeDefinition = {
    type: 'automation-benchmark-email-classic',
    category: 'marketing',
    label: 'Benchmark Email Classic',
    description: 'Manage Classic contact lists, subscribers, email campaign drafts and reports',
    keywords: ['benchmark', 'classic', 'email marketing', 'newsletter', 'subscribers'],
    Icon: BenchmarkEmailClassicIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={BenchmarkEmailClassicIcon} iconColor="" />),
};
