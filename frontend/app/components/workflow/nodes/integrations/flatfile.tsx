import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const FlatfileIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/flatfile.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const FlatfileNode: NodeDefinition = {
    type: 'automation-flatfile', category: 'developer-tools', label: 'Flatfile',
    description: 'Manage import spaces, workbooks, sheets, records, files and jobs',
    Icon: FlatfileIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={FlatfileIcon} iconColor="" />),
};
