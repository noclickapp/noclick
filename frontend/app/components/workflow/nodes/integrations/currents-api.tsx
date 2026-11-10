import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const CurrentsApiIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/currents-api.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const CurrentsApiNode: NodeDefinition = {
    type: 'automation-currents-api', category: 'content-research', label: 'Currents API',
    description: 'Search news, get headlines and discover language, region and category filters',
    Icon: CurrentsApiIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={CurrentsApiIcon} iconColor="" />),
};
