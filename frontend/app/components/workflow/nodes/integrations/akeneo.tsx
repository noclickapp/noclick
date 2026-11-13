import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';
import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';

const AkeneoIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/akeneo.svg" className={className} style={style} />
);

export const AkeneoNode: NodeDefinition = {
    type: 'automation-akeneo', category: 'ecommerce', label: 'Akeneo PIM REST API',
    description: 'Sync products, models, categories and families; watch product creation, updates and deletion',
    Icon: AkeneoIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={AkeneoIcon} iconColor="" />),
};
