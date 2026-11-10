// Defines the Cabinpanda node for the workflow canvas and integration catalog.
// Its forms category and official icon make the new integration discoverable.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const CabinpandaIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/cabinpanda.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const CabinpandaNode: NodeDefinition = {
    type: 'automation-cabinpanda', category: 'forms', label: 'Cabinpanda',
    description: 'Manage forms, submissions, templates and respondent notifications',
    Icon: CabinpandaIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={CabinpandaIcon} iconColor="" />),
};
