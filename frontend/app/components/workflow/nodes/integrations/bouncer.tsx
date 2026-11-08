import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const BouncerIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/bouncer.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const BouncerNode: NodeDefinition = {
    type: 'automation-bouncer', label: 'Bouncer',
    description: 'Verify emails and domains, process batches, and check email toxicity',
    keywords: ['email verification', 'email validation', 'deliverability', 'bulk email', 'toxicity'],
    Icon: BouncerIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={BouncerIcon} iconColor="" />),
};
