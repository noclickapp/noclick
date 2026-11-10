import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const TombaIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/tomba.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const TombaNode: NodeDefinition = {
    type: 'automation-tomba', category: 'crm-sales', label: 'Tomba',
    description: 'Find and verify emails, enrich domains, and manage leads and lists',
    Icon: TombaIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={TombaIcon} iconColor="" />),
};
