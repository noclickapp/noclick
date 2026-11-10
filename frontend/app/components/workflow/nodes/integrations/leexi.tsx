import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const LeexiIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/leexi.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const LeexiNode: NodeDefinition = {
    type: 'automation-leexi', label: 'Leexi',
    category: 'meetings',
    description: 'Manage calls, notes, meeting assistants, teams and users',
    Icon: LeexiIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={LeexiIcon} iconColor="" />),
};
