import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const PloidIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/ploid.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const PloidNode: NodeDefinition = {
    type: 'automation-ploid', category: 'hr-recruiting', label: 'Ploid',
    description: 'Search and enrich people, automate monitors and research datasets',
    Icon: PloidIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={PloidIcon} iconColor="" />),
};
