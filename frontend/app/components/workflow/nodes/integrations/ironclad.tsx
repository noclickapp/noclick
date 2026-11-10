import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const IroncladIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/ironclad.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const IroncladNode: NodeDefinition = {
    type: 'automation-ironclad', category: 'documents', label: 'Ironclad',
    description: 'Launch and manage contract workflows, records, comments and entities',
    keywords: ['contracts', 'CLM', 'legal', 'agreements'],
    Icon: IroncladIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={IroncladIcon} iconColor="" />),
};
