import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const LushaIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/lusha.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' } as CSSProperties} />
);

export const LushaNode: NodeDefinition = {
    type: 'automation-lusha',
    category: 'crm-sales',
    label: 'Lusha',
    description: 'Search and enrich contacts and companies, prospect and manage tables',
    keywords: ['sales intelligence', 'lead enrichment', 'prospecting'],
    Icon: LushaIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={LushaIcon} iconColor="" />),
};
