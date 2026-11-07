import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

// Official Qovery wordmark, preserved unchanged from the vendor asset.
const QoveryIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/qovery.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const QoveryNode: NodeDefinition = {
    type: 'automation-qovery',
    label: 'Qovery',
    description: 'Organization, project, environment, cluster and deployment metadata',
    Icon: QoveryIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={QoveryIcon} iconColor="" />),
};
