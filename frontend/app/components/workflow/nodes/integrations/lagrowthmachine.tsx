// La Growth Machine's self-registering canvas definition and provider icon.
// Configuration and credentials come from the generated backend schema.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const LagrowthmachineIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/lagrowthmachine.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const LagrowthmachineNode: NodeDefinition = {
    type: 'automation-lagrowthmachine', category: 'crm-sales', label: 'La Growth Machine',
    description: 'Manage outreach audiences, leads, campaigns and conversation replies',
    keywords: ['lagrowthmachine', 'LGM', 'sales', 'outreach', 'LinkedIn'],
    Icon: LagrowthmachineIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={LagrowthmachineIcon} iconColor="" />),
};
