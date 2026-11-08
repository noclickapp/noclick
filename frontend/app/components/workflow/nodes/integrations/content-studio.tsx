// Provides Content Studio in the workflow palette and canvas.
// The provider's published icon identifies its publishing and workspace actions.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const ContentStudioIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/content-studio.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const ContentStudioNode: NodeDefinition = {
    type: 'automation-content-studio', label: 'Content Studio',
    category: 'social-media',
    description: 'Create and schedule social posts; manage labels, campaigns and content categories',
    keywords: ['ContentStudio', 'social media', 'publishing', 'content calendar'],
    Icon: ContentStudioIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={ContentStudioIcon} iconColor="" />),
};
