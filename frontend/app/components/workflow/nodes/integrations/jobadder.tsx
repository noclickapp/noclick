import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const JobAdderIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/jobadder.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const JobAdderNode: NodeDefinition = {
    type: 'automation-jobadder', category: 'hr-recruiting', label: 'JobAdder',
    description: 'Manage candidates, companies, contacts, jobs, placements and recruiting notes',
    Icon: JobAdderIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={JobAdderIcon} iconColor="" />),
};
