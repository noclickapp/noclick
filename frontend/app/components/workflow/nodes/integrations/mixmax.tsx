import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const MixmaxIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/mixmax.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const MixmaxNode: NodeDefinition = {
    type: 'automation-mixmax', category: 'crm-sales', label: 'Mixmax',
    description: 'Automate sequences, email drafts, templates and unsubscribes',
    Icon: MixmaxIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={MixmaxIcon} iconColor="" />),
};
