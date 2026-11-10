// Registers Tapfiliate in the workflow palette and canvas using its official icon.
// The generated backend schema supplies the operation and credential forms.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const TapfiliateIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/tapfiliate.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const TapfiliateNode: NodeDefinition = {
    type: 'automation-tapfiliate', category: 'marketing', label: 'Tapfiliate',
    description: 'Manage affiliates, referred customers, conversions and commissions',
    keywords: ['affiliate marketing', 'referrals', 'commissions', 'conversion tracking'],
    Icon: TapfiliateIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={TapfiliateIcon} iconColor="" />),
};
