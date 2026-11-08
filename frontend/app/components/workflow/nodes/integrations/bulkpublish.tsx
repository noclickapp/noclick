// Bulkpublish exposes social publishing and reporting with a pasted API key.
// This definition makes its generated operations available in the workflow editor.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const BulkpublishIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/bulkpublish.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const BulkpublishNode: NodeDefinition = {
    type: 'automation-bulkpublish', category: 'social-media', label: 'Bulkpublish',
    description: 'Create and schedule social posts, manage media and labels, and read analytics',
    Icon: BulkpublishIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={BulkpublishIcon} iconColor="" />),
};
