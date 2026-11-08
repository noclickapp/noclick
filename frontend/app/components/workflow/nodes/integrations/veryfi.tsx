import { memo, type CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const VeryfiIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/veryfi.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const VeryfiNode: NodeDefinition = {
    type: 'automation-veryfi',
    label: 'Veryfi',
    description: 'Receipt and invoice processing, document summaries and tags',
    category: 'documents',
    Icon: VeryfiIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={VeryfiIcon} iconColor="" />),
};
