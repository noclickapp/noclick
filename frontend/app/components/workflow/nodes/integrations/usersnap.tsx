// Adds Usersnap feedback submission and project reporting to the integration catalog.
// Its icon is the publisher's asset, with provenance recorded beside the file.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const UsersnapIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/usersnap.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' } as CSSProperties} />
);

export const UsersnapNode: NodeDefinition = {
    type: 'automation-usersnap',
    category: 'support',
    label: 'Usersnap',
    description: 'Submit customer feedback, find feedback, and report on projects',
    keywords: ['bugs', 'customer feedback', 'NPS', 'surveys'],
    Icon: UsersnapIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={UsersnapIcon} iconColor="" />),
};
