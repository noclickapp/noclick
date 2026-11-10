import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const OwlerIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/owler.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const OwlerNode: NodeDefinition = {
    type: 'automation-owler', category: 'crm-sales', label: 'Owler',
    description: 'Look up company profiles and competitors, read news, and monitor new company news.',
    keywords: ['company intelligence', 'competitive intelligence', 'funding', 'acquisitions'],
    Icon: OwlerIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={OwlerIcon} iconColor="" />),
};
