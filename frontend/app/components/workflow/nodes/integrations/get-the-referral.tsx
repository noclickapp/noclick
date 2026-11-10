import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const GetTheReferralIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/get-the-referral.svg" dark="/icons/get-the-referral-dark.svg" className={className} style={style} />
);

export const GetTheReferralNode: NodeDefinition = {
    type: 'automation-get-the-referral', category: 'crm-sales', label: 'Get The Referral',
    description: 'Manage advocates, referral leads, contacts and sales reps; read referral payments',
    keywords: ['GTR', 'referrals', 'Referral Boost'],
    Icon: GetTheReferralIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={GetTheReferralIcon} iconColor="" />),
};
