import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const TelnyxIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/telnyx.svg" className={className} style={style} />
);

export const TelnyxNode: NodeDefinition = {
    type: 'automation-telnyx', category: 'communication', label: 'Telnyx',
    description: 'Send messages, manage messaging profiles and phone numbers, and read account balance',
    Icon: TelnyxIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={TelnyxIcon} iconColor="" />),
};
