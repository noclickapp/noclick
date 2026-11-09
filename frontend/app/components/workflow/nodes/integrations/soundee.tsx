import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const SoundeeIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/soundee.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const SoundeeNode: NodeDefinition = {
    type: 'automation-soundee', category: 'media', label: 'Soundee',
    description: 'Manage coupons and read sales, captured emails and abandoned carts',
    Icon: SoundeeIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={SoundeeIcon} iconColor="" />),
};
