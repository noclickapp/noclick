import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';
import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';

const SureVoIPIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/surevoip.svg" dark="/icons/surevoip-dark.svg" className={className} style={style} />
);

export const SureVoIPNode: NodeDefinition = {
    type: 'automation-surevoip', category: 'communication', label: 'SureVoIP',
    description: 'Create calls, manage announcements, and read customers, messages and billing',
    keywords: ['SureVoIP RESTful API', 'VoIP', 'SIP', 'telephony'],
    Icon: SureVoIPIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={SureVoIPIcon} iconColor="" />),
};
