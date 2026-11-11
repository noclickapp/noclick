// Registers EVE Swagger Interface in the canvas and integration catalog.
// Uses the official EVE favicon mark while the generated backend schema supplies its operations and credential form.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';
import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';

const EvetechIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/evetech.svg" dark="/icons/evetech-dark.svg" className={className} style={{ ...style, objectFit: 'contain' }} />
);

export const EvetechNode: NodeDefinition = {
    type: 'automation-evetech', label: 'EVE Swagger Interface', category: 'industry',
    description: 'EVE Online markets, character assets, wallet, mail and calendar; poll for new mail',
    Icon: EvetechIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo(function EvetechNodeComponent(props: NodeProps) {
        return <AutomationNode {...props} Icon={EvetechIcon} iconColor="" />;
    }),
};
