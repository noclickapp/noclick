import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';


import type { CSSProperties as BrandCSSProperties } from 'react';
// Vector brand artwork from https://vervoe.com
export const VervoeIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <img src="/icons/vervoe.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as BrandCSSProperties} />
);

export const VervoeNode: NodeDefinition = {
    type: 'automation-vervoe',
    label: 'Vervoe',
    description: 'Vervoe assessment and application metadata with internal folder management',
    category: 'hr-recruiting',
    keywords: ['Vervoe', 'assessments', 'applications', 'folders', 'recruiting'],
    Icon: VervoeIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: (props: NodeProps) => <AutomationNode {...props} Icon={VervoeIcon} iconColor="" />,
};
