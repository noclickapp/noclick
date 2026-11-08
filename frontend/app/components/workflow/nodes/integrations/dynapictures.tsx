import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const DynapicturesIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/dynapictures.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const DynapicturesNode: NodeDefinition = {
    type: 'automation-dynapictures', category: 'media', label: 'DynaPictures',
    description: 'Generate images, manage templates, designs, media, workspaces and webhooks',
    Icon: DynapicturesIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={DynapicturesIcon} iconColor="" />),
};
