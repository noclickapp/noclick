// Upload Post publishes content through one social media API.
// This definition makes its operations available in the workflow catalog.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const UploadPostIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/upload-post.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const UploadPostNode: NodeDefinition = {
    type: 'automation-upload-post', category: 'social-media', label: 'Upload Post',
    description: 'Publish posts and videos, manage schedules and queues, and read social analytics',
    Icon: UploadPostIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={UploadPostIcon} iconColor="" />),
};
