import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const BreezyHRIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/breezy-hr.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const BreezyHRNode: NodeDefinition = {
    type: 'automation-breezy-hr', category: 'hr-recruiting', label: 'Breezy HR',
    description: 'Manage recruiting companies, positions, candidates, pipeline stages and notes',
    Icon: BreezyHRIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={BreezyHRIcon} iconColor="" />),
};
