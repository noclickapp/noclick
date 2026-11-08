/** Discover ServiceTitan in the workflow catalog and canvas. Uses the official provider icon to identify CRM operations. */
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const ServiceTitanIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/servicetitan.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const ServiceTitanNode: NodeDefinition = {
    type: 'automation-servicetitan', category: 'industry', label: 'ServiceTitan',
    description: 'Read and update CRM customers, locations, leads, contacts and notes',
    Icon: ServiceTitanIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={ServiceTitanIcon} iconColor="" />),
};
