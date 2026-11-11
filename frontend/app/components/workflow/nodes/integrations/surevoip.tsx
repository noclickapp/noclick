import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const SureVoIPIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <>
        <img src="/icons/surevoip.svg" alt="" aria-hidden="true" className={`${className ?? ''} dark:hidden`} style={style} />
        <img src="/icons/surevoip-dark.svg" alt="" aria-hidden="true" className={`${className ?? ''} hidden dark:block`} style={style} />
    </>
);

export const SureVoIPNode: NodeDefinition = {
    type: 'automation-surevoip', category: 'communication', label: 'SureVoIP',
    description: 'Create calls, manage announcements, and read customers, messages and billing',
    keywords: ['SureVoIP RESTful API', 'VoIP', 'SIP', 'telephony'],
    Icon: SureVoIPIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={SureVoIPIcon} iconColor="" />),
};
