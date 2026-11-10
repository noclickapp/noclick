import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

// Unmodified brand asset from https://www.vdocipher.com/.
const VdoCipherIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/vdocipher-brand.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const VdoCipherNode: NodeDefinition = {
    type: 'automation-vdocipher',
    label: 'VdoCipher',
    description: 'Video metadata, tags, upload policies and playback authorization',
    category: 'media',
    Icon: VdoCipherIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={VdoCipherIcon} iconColor="" />),
};
