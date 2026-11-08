import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const WizaIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/wiza.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const WizaNode: NodeDefinition = {
    type: 'automation-wiza', label: 'Wiza',
    description: 'Enrich contacts and companies, manage enrichment lists, search prospects and check credits',
    keywords: ['email finder', 'phone numbers', 'sales prospecting', 'lead enrichment'],
    Icon: WizaIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={WizaIcon} iconColor="" />),
};
