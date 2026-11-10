import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const BetterContactIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/bettercontact.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const BetterContactNode: NodeDefinition = {
    type: 'automation-bettercontact', category: 'crm-sales', label: 'BetterContact',
    description: 'Enrich contacts and company profiles, find leads and track search results',
    keywords: ['Bettercontact', 'lead enrichment', 'email finder', 'prospecting'],
    Icon: BetterContactIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={BetterContactIcon} iconColor="" />),
};
