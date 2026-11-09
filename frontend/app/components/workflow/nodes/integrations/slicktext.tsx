import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const SlickTextIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/slicktext.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const SlickTextNode: NodeDefinition = {
    type: 'automation-slicktext', category: 'marketing', label: 'SlickText',
    description: 'Manage contacts, lists and SMS campaigns on the new SlickText platform',
    Icon: SlickTextIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={SlickTextIcon} iconColor="" />),
};
