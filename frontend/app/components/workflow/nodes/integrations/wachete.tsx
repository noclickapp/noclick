import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const WacheteIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/wachete.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const WacheteNode: NodeDefinition = {
    type: 'automation-wachete', label: 'Wachete',
    description: 'Monitor pages and manage folders, change history and notifications',
    Icon: WacheteIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={WacheteIcon} iconColor="" />),
};
