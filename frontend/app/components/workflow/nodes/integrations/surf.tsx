import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const SurfIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/surf.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const SurfNode: NodeDefinition = {
    type: 'automation-surf', category: 'finance-accounting', label: 'Surf',
    description: 'Research crypto markets, projects, wallets and news, and manage onchain SQL jobs',
    Icon: SurfIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={SurfIcon} iconColor="" />),
};
