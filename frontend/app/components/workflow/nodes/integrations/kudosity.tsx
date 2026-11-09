import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const KudosityIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/kudosity.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const KudosityNode: NodeDefinition = {
    type: 'automation-kudosity', category: 'communication', label: 'Kudosity',
    description: 'Send and inspect SMS, MMS, WhatsApp and RCS messages; manage webhooks',
    Icon: KudosityIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={KudosityIcon} iconColor="" />),
};
