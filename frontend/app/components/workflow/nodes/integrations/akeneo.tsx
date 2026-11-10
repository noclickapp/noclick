import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const AkeneoIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/akeneo.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const AkeneoNode: NodeDefinition = {
    type: 'automation-akeneo', category: 'ecommerce', label: 'Akeneo PIM REST API',
    description: 'Sync products, models, categories and families; watch product creation, updates and deletion',
    Icon: AkeneoIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={AkeneoIcon} iconColor="" />),
};
