import { memo } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition } from '~/components/workflow/nodes/types';

const ZenotiIcon = ({ className, style }: { className?: string; style?: React.CSSProperties }) => (
    <img src="/icons/zenoti.svg" alt="" aria-hidden="true" className={className} style={{ ...style, objectFit: 'contain' }} />
);
const ZenotiNodeComponent = (props: NodeProps) => <AutomationNode {...props} Icon={ZenotiIcon} iconColor="" />;
export const ZenotiNode: NodeDefinition = {
    type: 'automation-zenoti', label: 'Zenoti',
    description: 'Read center, service and guest metadata or update scoped guest CRM fields',
    Icon: ZenotiIcon, iconColor: '', dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo(ZenotiNodeComponent),
};
