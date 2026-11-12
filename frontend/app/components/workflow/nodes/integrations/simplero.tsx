import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';
import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';

const SimpleroIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/simplero.svg" dark="/icons/simplero-dark.svg" className={className} style={{ ...style, objectFit: 'contain' }} />
);

export const SimpleroNode: NodeDefinition = {
    type: 'automation-simplero', category: 'courses', label: 'Simplero',
    description: 'Manage contacts, tags, automations and list subscriptions; read products and purchases',
    Icon: SimpleroIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={SimpleroIcon} iconColor="" />),
};
