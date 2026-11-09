// Zadarma joins the discovered integration catalog and workflow canvas.
// Its schema and credential metadata are generated from the backend node.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const ZadarmaIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/zadarma.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const ZadarmaNode: NodeDefinition = {
    type: 'automation-zadarma', category: 'communication', label: 'Zadarma',
    description: 'Automate calls, SMS, SIP numbers, PBX extensions and call statistics',
    Icon: ZadarmaIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={ZadarmaIcon} iconColor="" />),
};
