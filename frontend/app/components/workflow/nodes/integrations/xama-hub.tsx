import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const XamaHubIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/xama-hub.png" dark="/icons/xama-hub-dark.png" className={className} style={style} />
);

export const XamaHubNode: NodeDefinition = {
    type: 'automation-xama-hub', category: 'crm-sales', label: 'Xama Hub',
    description: 'Manage accounts, contacts, AML reports, onboarding and risk assessments',
    keywords: ['Xama', 'AML', 'compliance', 'KYC', 'client onboarding'],
    Icon: XamaHubIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={XamaHubIcon} iconColor="" />),
};
