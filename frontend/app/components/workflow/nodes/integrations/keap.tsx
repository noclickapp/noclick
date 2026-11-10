// Keap's canvas definition is discovered from its integration filename.
// Its component loads only when a Keap node appears on the canvas.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition } from '~/components/workflow/nodes/types';

// Keap brand artwork; source recorded in the icon provenance sidecar.
const KeapIcon = ({
    className,
    style,
}: {
    className?: string;
    style?: CSSProperties;
}) => (
    <img
        src="/icons/keap.svg"
        alt=""
        aria-hidden="true"
        className={className}
        style={{ ...style, objectFit: 'contain' }}
    />
);

const KeapNodeComponent = (props: NodeProps) => (
    <AutomationNode {...props} Icon={KeapIcon} iconColor="" />
);

export const KeapNode: NodeDefinition = {
    type: 'automation-keap',
    label: 'Keap',
    description: 'Contacts, opportunities, orders, campaigns, tasks, and automations',
    category: 'crm-sales',
    Icon: KeapIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo(KeapNodeComponent),
};
