import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const WistiaIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/wistia.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const WistiaNode: NodeDefinition = {
    type: 'automation-wistia', category: 'media', label: 'Wistia',
    description: 'Manage Wistia media, folders, tags and captions; import videos and read statistics',
    Icon: WistiaIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={WistiaIcon} iconColor="" />),
};
