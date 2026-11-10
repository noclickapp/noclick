import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const Digistore24Icon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <>
        <img src="/icons/digistore24.svg" alt="" aria-hidden="true" className={`dark:hidden ${className ?? ''}`} style={style} />
        <img src="/icons/digistore24-dark.svg" alt="" aria-hidden="true" className={`${className ?? ''} hidden dark:block`} style={style} />
    </>
);

export const Digistore24Node: NodeDefinition = {
    type: 'automation-digistore24', category: 'ecommerce', label: 'Digistore24',
    description: 'Trigger workflows from order events; manage buyers, purchases, products and billing',
    Icon: Digistore24Icon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={Digistore24Icon} iconColor="" />),
};
