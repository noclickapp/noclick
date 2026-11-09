import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const SmolMachinesIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/smol-machines.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const SmolMachinesNode: NodeDefinition = {
    type: 'automation-smol-machines', category: 'cloud-hosting', label: 'Smol Machines',
    description: 'Manage machines, run commands and code, track jobs and scale groups',
    Icon: SmolMachinesIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={SmolMachinesIcon} iconColor="" />),
};
