import type { NodeProps } from '@xyflow/react';
import type { CSSProperties } from 'react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const LinkAceIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/linkace.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);
export const LinkAceNode: NodeDefinition = {
    type: 'automation-linkace', label: 'LinkAce',
    description: 'Read current list and tag metadata',
    keywords: ['LinkAce', 'list metadata', 'tag metadata', 'visibility', 'catalog'],
    Icon: LinkAceIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: (props: NodeProps) => <AutomationNode {...props} Icon={LinkAceIcon} iconColor="" />,
};
