import { memo, type CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

export function HumanitecIcon({ className, style }: { className?: string; style?: CSSProperties }) {
    return <img src="/icons/humanitec.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} draggable={false} />;
}
export const HumanitecNode: NodeDefinition = {
    type: 'automation-humanitec', label: 'Humanitec',
    description: 'Organization, application, environment, deployment and pipeline metadata, with confirmed application creation and name updates.',
    Icon: HumanitecIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={HumanitecIcon} iconColor="" />),
};
