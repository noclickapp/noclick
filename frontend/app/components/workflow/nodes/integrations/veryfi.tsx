import { memo, type CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const VeryfiIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/veryfi.svg" dark="/icons/veryfi-dark.svg" className={className} style={style} />
);

export const VeryfiNode: NodeDefinition = {
    type: 'automation-veryfi',
    label: 'Veryfi',
    description: 'Receipt and invoice processing, document summaries and tags',
    category: 'documents',
    Icon: VeryfiIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={VeryfiIcon} iconColor="" />),
};
