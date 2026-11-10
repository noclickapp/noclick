// Deel workforce and organization automation node.
// Uses the provider's unmodified official logo so the integration is recognizable.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const DeelIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/deel.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);
const DeelNodeComponent = (props: NodeProps) => (
    <AutomationNode {...props} Icon={DeelIcon} iconColor="" />
);
export const DeelNode: NodeDefinition = {
    type: 'automation-deel',
    label: 'Deel',
    description: 'Sync employee and contractor records, departments, and reporting relationships',
    category: 'hr-recruiting',
    keywords: ['HRIS', 'employees', 'contractors', 'departments', 'organization'],
    Icon: DeelIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo(DeelNodeComponent),
};
