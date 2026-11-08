import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const GenderApiIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/gender-api.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const GenderApiNode: NodeDefinition = {
    type: 'automation-gender-api', label: 'Gender Api',
    description: 'Query gender and country of origin from names and emails, and monitor account credits',
    keywords: ['Gender-API', 'name enrichment', 'country of origin'],
    Icon: GenderApiIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={GenderApiIcon} iconColor="" />),
};
