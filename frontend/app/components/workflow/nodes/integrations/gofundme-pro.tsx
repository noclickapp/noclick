import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const GoFundMeProIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/gofundme-pro.svg" className={className} style={style} />
);

export const GoFundMeProNode: NodeDefinition = {
    type: 'automation-gofundme-pro', category: 'nonprofit', label: 'GoFundMe Pro',
    description: 'Manage supporters, designations and donation reporting; read campaigns, recurring plans and fundraising teams.',
    keywords: ['Classy', 'donations', 'fundraising', 'nonprofit'],
    Icon: GoFundMeProIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={GoFundMeProIcon} iconColor="" />),
};
