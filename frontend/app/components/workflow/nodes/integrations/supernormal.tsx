// Native Supernormal identity, calendar and existing recording/transcript reads.
// The generated provider schema supplies its scoped credential and privacy defaults.
import { memo } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';
import { SupernormalIcon } from '~/components/icons/SupernormalIcon';

const SupernormalNodeComponent = (props: NodeProps) => <AutomationNode {...props} Icon={SupernormalIcon} iconColor="" />;
export const SupernormalNode: NodeDefinition = {
    type: 'automation-supernormal', category: 'meetings', label: 'Supernormal',
    description: 'Meeting-service identity, calendar and recording metadata with selected transcript text',
    Icon: SupernormalIcon, iconColor: '', dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo(SupernormalNodeComponent),
};
