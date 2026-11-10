// Coassemble's own definition makes its node discoverable in the workflow editor.
// The provider's official site icon identifies its headless course API.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const CoassembleIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/coassemble.svg" dark="/icons/coassemble-dark.svg" className={className} style={style} />
);

export const CoassembleNode: NodeDefinition = {
    type: 'automation-coassemble', category: 'courses', label: 'Coassemble',
    description: 'Manage courses, collections, learners and course tracking in Coassemble',
    keywords: ['learning', 'training', 'lms', 'headless', 'courses'],
    Icon: CoassembleIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={CoassembleIcon} iconColor="" />),
};
