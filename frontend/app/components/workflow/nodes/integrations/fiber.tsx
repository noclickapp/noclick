import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const FiberIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/fiber.svg" dark="/icons/fiber-dark.svg" className={className} style={style} />
);

export const FiberNode: NodeDefinition = {
    type: 'automation-fiber', category: 'crm-sales', label: 'Fiber',
    description: 'Find companies and people, reveal work emails, and manage audiences and enrichment',
    keywords: ['Fiber AI', 'prospecting', 'B2B', 'sales enrichment', 'leads'],
    Icon: FiberIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={FiberIcon} iconColor="" />),
};
