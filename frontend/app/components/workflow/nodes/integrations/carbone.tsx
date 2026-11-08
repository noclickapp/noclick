import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const CarboneIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/carbone.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const CarboneNode: NodeDefinition = {
    type: 'automation-carbone', label: 'Carbone',
    description: 'Generate and convert documents; manage templates, versions, categories and tags',
    Icon: CarboneIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={CarboneIcon} iconColor="" />),
};
