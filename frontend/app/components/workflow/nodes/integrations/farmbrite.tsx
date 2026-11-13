import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';
import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';

const FarmbriteIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/farmbrite.svg" dark="/icons/farmbrite-dark.svg" className={className} style={style} />
);

export const FarmbriteNode: NodeDefinition = {
    type: 'automation-farmbrite', category: 'industry', label: 'Farmbrite',
    description: 'Manage farm tasks, livestock, contacts and orders, and watch for farm record changes',
    Icon: FarmbriteIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={FarmbriteIcon} iconColor="" />),
};
