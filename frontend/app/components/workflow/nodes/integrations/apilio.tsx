import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const ApilioIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/apilio.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' } as CSSProperties} />
);

export const ApilioNode: NodeDefinition = {
    type: 'automation-apilio', category: 'industry', label: 'Apilio',
    description: 'Read and update variables, inspect conditions and control Logicblocks',
    Icon: ApilioIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={ApilioIcon} iconColor="" />),
};
