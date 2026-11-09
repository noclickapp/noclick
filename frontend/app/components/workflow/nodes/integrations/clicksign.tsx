import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const ClicksignIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/clicksign.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const ClicksignNode: NodeDefinition = {
    type: 'automation-clicksign', category: 'documents', label: 'Clicksign',
    description: 'Create envelopes, upload documents, manage signers and send signature requests',
    Icon: ClicksignIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={ClicksignIcon} iconColor="" />),
};
