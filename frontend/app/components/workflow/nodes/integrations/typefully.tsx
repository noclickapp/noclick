// Typefully exposes social publishing actions in the workflow catalog.
// The shared automation component renders its generated operation schemas.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const TypefullyIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/typefully.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const TypefullyNode: NodeDefinition = {
    type: 'automation-typefully',
    label: 'Typefully',
    description: 'Manage social drafts, publishing, media, tags and posting queues',
    category: 'social-media',
    keywords: ['Twitter', 'X', 'LinkedIn', 'Threads', 'Bluesky', 'Mastodon', 'Substack', 'social media'],
    Icon: TypefullyIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={TypefullyIcon} iconColor="" />),
};
