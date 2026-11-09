// Registers Encircle in the workflow canvas and integration catalog.
// The backend-generated schema supplies the claim operations and bearer-token form.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const EncircleIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/encircle.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const EncircleNode: NodeDefinition = {
    type: 'automation-encircle', category: 'industry', label: 'Encircle',
    description: 'Manage restoration claims, assignments, structures, rooms and notes',
    Icon: EncircleIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={EncircleIcon} iconColor="" />),
};
