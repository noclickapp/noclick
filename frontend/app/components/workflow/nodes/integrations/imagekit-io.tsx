import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const ImageKitIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/imagekit-io.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const ImageKitNode: NodeDefinition = {
    type: 'automation-imagekit-io', category: 'media', label: 'ImageKit.io',
    description: 'Upload, search and manage media files, versions, tags, folders and CDN cache',
    keywords: ['Imagekit Io', 'imagekit_io', 'digital asset management', 'CDN'],
    Icon: ImageKitIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={ImageKitIcon} iconColor="" />),
};
