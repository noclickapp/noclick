import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const PodiumIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <>
        <img src="/icons/podium.svg" alt="" aria-hidden="true" className={`${className ?? ''} dark:hidden`}
            style={{ ...style, objectFit: 'contain' } as CSSProperties} />
        <img src="/icons/podium-dark.svg" alt="" aria-hidden="true" className={`${className ?? ''} hidden dark:block`}
            style={{ ...style, objectFit: 'contain' } as CSSProperties} />
    </>
);

export const PodiumNode: NodeDefinition = {
    type: 'automation-podium', category: 'communication', label: 'Podium',
    description: 'Send messages, manage conversations and invoices, and read reviews and locations',
    Icon: PodiumIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={PodiumIcon} iconColor="" />),
};
