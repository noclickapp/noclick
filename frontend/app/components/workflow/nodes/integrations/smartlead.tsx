import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const SmartleadIcon = ({
    className,
    style,
}: {
    className?: string;
    style?: CSSProperties;
}) => (
    <img
        src="/icons/smartlead.svg"
        alt=""
        aria-hidden="true"
        className={className}
        style={{ ...style, objectFit: 'contain' }}
    />
);

export const SmartleadNode: NodeDefinition = {
    type: 'automation-smartlead',
    category: 'crm-sales',
    label: 'Smartlead',
    description:
        'Read outreach analytics, manage inbox leads and tag email accounts',
    Icon: SmartleadIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => (
        <AutomationNode {...props} Icon={SmartleadIcon} iconColor="" />
    )),
};
