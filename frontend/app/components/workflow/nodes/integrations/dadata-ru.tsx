// Registers Dadata Ru in the workflow canvas and integration catalog.
// The backend generates its operation forms; the official brand asset is pinned beside its provenance.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const DadataRuIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/dadata-ru.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const DadataRuNode: NodeDefinition = {
    type: 'automation-dadata-ru', category: 'content-research', label: 'Dadata Ru',
    description: 'Standardize contact data, find companies and addresses, and check account usage',
    Icon: DadataRuIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={DadataRuIcon} iconColor="" />),
};
