import { memo } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';
import type { CSSProperties } from 'react';

const FrontIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/front-preferred-brand.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const FrontNode: NodeDefinition = {
    type: 'automation-front',
    label: 'Front',
    category: 'support',
    description: 'Shared inbox, conversations, messages, contacts, and analytics',
    Icon: FrontIcon,
    iconColor: 'text-blue-500',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => (
        <AutomationNode {...props} Icon={FrontIcon} iconColor="text-blue-500" />
    )),
};
