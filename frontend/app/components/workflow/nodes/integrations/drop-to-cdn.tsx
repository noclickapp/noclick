import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const DropToCdnIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/drop-to-cdn.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const DropToCdnNode: NodeDefinition = {
    type: 'automation-drop-to-cdn', category: 'databases-storage', label: 'Drop To Cdn',
    description: 'Upload and manage public CDN files and publish HTML pages',
    Icon: DropToCdnIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={DropToCdnIcon} iconColor="" />),
};
