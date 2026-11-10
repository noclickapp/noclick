import { memo } from 'react';
import type { CSSProperties } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition } from '~/components/workflow/nodes/types';

// Integration icon carried over from the original Zoho CRM implementation.
const ZohoCRMIcon = ({
    className,
    style,
}: {
    className?: string;
    style?: CSSProperties;
}) => (
    <img
        src="/icons/zoho-crm.svg"
        alt=""
        aria-hidden="true"
        className={className}
        style={{ ...style, objectFit: 'contain' }}
    />
);

const ZohoCRMNodeComponent = (props: NodeProps) => (
    <AutomationNode {...props} Icon={ZohoCRMIcon} iconColor="" />
);

export const ZohoCRMNode: NodeDefinition = {
    type: 'automation-zoho-crm',
    label: 'Zoho CRM',
    description: 'Zoho CRM records and metadata',
    category: 'crm-sales',
    Icon: ZohoCRMIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo(ZohoCRMNodeComponent),
};
