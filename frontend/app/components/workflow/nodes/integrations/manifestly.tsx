// Registers Manifestly Checklists in the workflow canvas and integration catalog.
// The definition supplies its productivity category and official icon for automatic discovery.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const ManifestlyIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/manifestly.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const ManifestlyNode: NodeDefinition = {
    type: 'automation-manifestly', category: 'productivity', label: 'Manifestly Checklists',
    description: 'Start checklist runs, complete and assign steps, collect data, and react to run and step events',
    keywords: ['checklists', 'workflows', 'tasks'],
    Icon: ManifestlyIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={ManifestlyIcon} iconColor="" />),
};
