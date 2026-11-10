import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const IcypeasIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/icypeas.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const IcypeasNode: NodeDefinition = {
    type: 'automation-icypeas', category: 'crm-sales', label: 'Icypeas',
    description: 'Find and verify emails, enrich profiles and read search results',
    Icon: IcypeasIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={IcypeasIcon} iconColor="" />),
};
