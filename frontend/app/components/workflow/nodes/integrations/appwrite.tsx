import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const AppwriteIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/appwrite.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const AppwriteNode: NodeDefinition = {
    type: 'automation-appwrite', category: 'databases-storage', label: 'Appwrite',
    description: 'Automate database rows, users, files and functions with signed event triggers',
    Icon: AppwriteIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={AppwriteIcon} iconColor="" />),
};
