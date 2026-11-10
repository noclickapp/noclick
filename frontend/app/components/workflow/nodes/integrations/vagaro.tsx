// Native Vagaro Enterprise Business API metadata and profile updates.
// The generated form selects documented regional operations and server-only issued credentials.
// Booking, payments and employee assignment are outside this node.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition } from '~/components/workflow/nodes/types';

// Official logo from Vagaro API documentation.
const OfficialBrandIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/vagaro.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

const VagaroNodeComponent = (props: NodeProps) => <AutomationNode {...props} Icon={OfficialBrandIcon} iconColor="" />;

export const VagaroNode: NodeDefinition = {
    type: 'automation-vagaro',
    category: 'bookings',
    label: 'Vagaro',
    keywords: ['salon', 'spa', 'customers', 'employees', 'appointments'],
    description: 'Vagaro business metadata and profile updates',
    Icon: OfficialBrandIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo(VagaroNodeComponent),
};
