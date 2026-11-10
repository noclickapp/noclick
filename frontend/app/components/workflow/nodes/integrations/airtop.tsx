import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const AirtopIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/airtop.svg" dark="/icons/airtop-dark.svg" className={className} style={style} />
);

export const AirtopNode: NodeDefinition = {
    type: 'automation-airtop', category: 'ai', label: 'Airtop',
    description: 'Automate browser sessions, interact with pages and extract content',
    Icon: AirtopIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={AirtopIcon} iconColor="" />),
};
