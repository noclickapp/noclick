import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const FarmbriteIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/farmbrite.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const FarmbriteNode: NodeDefinition = {
    type: 'automation-farmbrite', category: 'industry', label: 'Farmbrite',
    description: 'Manage farm tasks, livestock, contacts and orders, and watch for farm record changes',
    Icon: FarmbriteIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={FarmbriteIcon} iconColor="" />),
};
