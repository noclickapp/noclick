import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const NiftyImagesIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/niftyimages.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const NiftyImagesNode: NodeDefinition = {
    type: 'automation-niftyimages', label: 'NiftyImages',
    category: 'marketing',
    description: 'Automate images, map locations, stores and records',
    Icon: NiftyImagesIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={NiftyImagesIcon} iconColor="" />),
};
