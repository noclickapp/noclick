import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const SnitcherIcon = ({
    className,
    style,
}: {
    className?: string;
    style?: CSSProperties;
}) => (
    <img
        src="/icons/snitcher.svg"
        alt=""
        aria-hidden="true"
        className={className}
        style={{ ...style, objectFit: 'contain' }}
    />
);

export const SnitcherNode: NodeDefinition = {
    type: 'automation-snitcher',
    category: 'crm-sales',
    label: 'Snitcher',
    description:
        'Automate visitor organisations, contacts, tags, custom fields, sessions and workspaces',
    Icon: SnitcherIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => (
        <AutomationNode {...props} Icon={SnitcherIcon} iconColor="" />
    )),
};
