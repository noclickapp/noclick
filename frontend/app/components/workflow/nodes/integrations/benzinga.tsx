import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const BenzingaIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/benzinga.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const BenzingaNode: NodeDefinition = {
    type: 'automation-benzinga', category: 'finance-accounting', label: 'Benzinga',
    description: 'Read market news, earnings calendars, quotes and financial statements',
    Icon: BenzingaIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={BenzingaIcon} iconColor="" />),
};
