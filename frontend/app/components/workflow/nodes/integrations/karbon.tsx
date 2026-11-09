/** Karbon exposes practice-management operations in workflows.
 * This definition pairs the backend schema with the official service icon. */
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';
const KarbonIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/karbon.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' } as CSSProperties} />
);
export const KarbonNode: NodeDefinition = {
    type: 'automation-karbon', category: 'finance-accounting', label: 'Karbon',
    description: 'Manage contacts, organizations, work items and notes in Karbon',
    keywords: ['accounting', 'practice management', 'clients', 'tasks'],
    Icon: KarbonIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={KarbonIcon} iconColor="" />),
};
