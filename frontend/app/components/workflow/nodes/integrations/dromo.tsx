import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const DromoIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/dromo.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const DromoNode: NodeDefinition = {
    type: 'automation-dromo', category: 'developer-tools', label: 'Dromo',
    description: 'Manage import schemas, uploads and headless spreadsheet imports',
    Icon: DromoIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={DromoIcon} iconColor="" />),
};
