import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const BouncifyIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/bouncify.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const BouncifyNode: NodeDefinition = {
    type: 'automation-bouncify', category: 'marketing', label: 'Bouncify',
    description: 'Verify emails, manage bulk verification lists and download clean results',
    Icon: BouncifyIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={BouncifyIcon} iconColor="" />),
};
