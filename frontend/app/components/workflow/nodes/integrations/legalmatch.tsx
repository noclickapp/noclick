import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const LegalMatchIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/legalmatch.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const LegalMatchNode: NodeDefinition = {
    type: 'automation-legalmatch', category: 'finance-accounting', label: 'LegalMatch',
    description: 'Manage QBI syncs, Salesforce mappings, payment banners and gap reviews',
    Icon: LegalMatchIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={LegalMatchIcon} iconColor="" />),
};
