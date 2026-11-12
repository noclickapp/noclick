// Defines Postal Data Api in the workflow palette and integrations catalog.
// The official publisher icon identifies its postal-code lookup and validation tools.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const PostalDataApiIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/postal-data-api.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const PostalDataApiNode: NodeDefinition = {
    type: 'automation-postal-data-api', category: 'developer-tools', label: 'Postal Data Api',
    description: 'Look up, validate and enrich postal codes worldwide',
    keywords: ['PostalDataPI', 'ZIP', 'postcode', 'address', 'geocoding'],
    Icon: PostalDataApiIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={PostalDataApiIcon} iconColor="" />),
};
