import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const ApiNinjasIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/api-ninjas.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const ApiNinjasNode: NodeDefinition = {
    type: 'automation-api-ninjas', category: 'developer-tools', label: 'API Ninjas',
    description: 'Validate contacts, enrich locations, query finance and analyze text',
    keywords: ['Api Ninjas', 'api_ninjas', 'email validation', 'geocoding', 'currency', 'text similarity'],
    Icon: ApiNinjasIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={ApiNinjasIcon} iconColor="" />),
};
