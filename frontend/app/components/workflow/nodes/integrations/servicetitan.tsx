/** Discover ServiceTitan in the workflow catalog and canvas. Uses the official provider icon to identify CRM operations. */
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const ServiceTitanIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/servicetitan.svg" dark="/icons/servicetitan-dark.svg" className={className} style={style} />
);

export const ServiceTitanNode: NodeDefinition = {
    type: 'automation-servicetitan', category: 'industry', label: 'ServiceTitan',
    description: 'Watch new or updated customers, locations and leads; read and update CRM records, contacts and notes',
    Icon: ServiceTitanIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={ServiceTitanIcon} iconColor="" />),
};
