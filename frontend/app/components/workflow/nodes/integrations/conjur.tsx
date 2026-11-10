import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const ConjurIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/conjur.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const ConjurNode: NodeDefinition = {
    type: 'automation-conjur', category: 'developer-tools', label: 'Conjur',
    description: 'Read and write Conjur secrets, policies, resources and role memberships',
    Icon: ConjurIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={ConjurIcon} iconColor="" />),
};
