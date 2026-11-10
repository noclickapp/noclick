/** Registers Lettr in the workflow canvas and integration catalog.
 * Uses the official provider icon to identify email and audience automation. */
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const LettrIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/lettr.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const LettrNode: NodeDefinition = {
    type: 'automation-lettr', category: 'communication', label: 'Lettr',
    description: 'Send and schedule email, manage domains, templates and contacts',
    Icon: LettrIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={LettrIcon} iconColor="" />),
};
