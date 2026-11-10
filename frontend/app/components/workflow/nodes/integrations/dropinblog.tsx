import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const DropInBlogIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/dropinblog.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' } as CSSProperties} />
);

export const DropInBlogNode: NodeDefinition = {
    type: 'automation-dropinblog', category: 'marketing', label: 'DropInBlog',
    description: 'Create and update blog posts, read authors and categories, and watch post updates',
    keywords: ['blog', 'publishing', 'SEO', 'content'],
    Icon: DropInBlogIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={DropInBlogIcon} iconColor="" />),
};
