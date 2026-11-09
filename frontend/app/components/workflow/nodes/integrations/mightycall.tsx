import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const MightyCallIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/mightycall.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain', backgroundColor: '#333', padding: 6, borderRadius: 8 }} />
);

export const MightyCallNode: NodeDefinition = {
    type: 'automation-mightycall', category: 'communication', label: 'MightyCall',
    description: 'Automate calls, voicemails, contacts, messages and availability',
    Icon: MightyCallIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={MightyCallIcon} iconColor="" />),
};
