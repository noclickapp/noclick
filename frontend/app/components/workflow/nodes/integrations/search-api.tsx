import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const SearchApiIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/search-api.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const SearchApiNode: NodeDefinition = {
    type: 'automation-search-api', category: 'content-research', label: 'Search Api',
    description: 'Search Google with date, location, language and device filters',
    Icon: SearchApiIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={SearchApiIcon} iconColor="" />),
};
