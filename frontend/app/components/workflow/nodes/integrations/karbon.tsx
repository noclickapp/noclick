/** Karbon exposes practice-management operations in workflows.
 * This definition pairs the backend schema with the official service icon. */
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';
import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const KarbonIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/karbon.svg" dark="/icons/karbon-dark.svg" className={className} style={style} />
);
export const KarbonNode: NodeDefinition = {
    type: 'automation-karbon', category: 'finance-accounting', label: 'Karbon',
    description: 'Start workflows from Karbon changes and manage contacts, work items and notes',
    keywords: ['accounting', 'practice management', 'clients', 'tasks'],
    Icon: KarbonIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={KarbonIcon} iconColor="" />),
};
