import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const ApilioIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/apilio.svg" dark="/icons/apilio-dark.svg" className={className} style={style} />
);

export const ApilioNode: NodeDefinition = {
    type: 'automation-apilio', category: 'industry', label: 'Apilio',
    description: 'Read and update variables, inspect conditions and control Logicblocks',
    Icon: ApilioIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={ApilioIcon} iconColor="" />),
};
