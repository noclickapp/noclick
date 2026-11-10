/** Defines the Text Request catalog entry and canvas icon.
 * Keeps the integration discoverable with its communication category and official mark. */
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const TextRequestIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/text-request.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const TextRequestNode: NodeDefinition = {
    type: 'automation-text-request', category: 'communication', label: 'Text Request',
    description: 'Send texts and manage contacts, conversations, groups, tags and scheduled messages',
    Icon: TextRequestIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={TextRequestIcon} iconColor="" />),
};
