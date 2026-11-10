import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const MatillionIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <>
        <img src="/icons/matillion.svg" alt="" aria-hidden="true" className={`${className ?? ''} dark:hidden`}
            style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
        <img src="/icons/matillion-dark.svg" alt="" aria-hidden="true" className={`${className ?? ''} hidden dark:block`}
            style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
    </>
);
const MatillionNodeComponent = (props: NodeProps) => <AutomationNode {...props} Icon={MatillionIcon} iconColor="" />;

export const MatillionNode: NodeDefinition = {
    type: 'automation-matillion', category: 'analytics-bi', label: 'Maia (Matillion)',
    description: 'Read scoped pipeline metadata and manage confirmed execution lifecycle',
    Icon: MatillionIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: MatillionNodeComponent,
};
