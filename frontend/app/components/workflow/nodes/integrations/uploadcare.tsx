import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const UploadcareIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/uploadcare.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const UploadcareNode: NodeDefinition = {
    type: 'automation-uploadcare', label: 'Uploadcare',
    category: 'media',
    description: 'Manage files, metadata, tags, groups and webhooks',
    Icon: UploadcareIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={UploadcareIcon} iconColor="" />),
};
