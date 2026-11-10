import { memo } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition } from '~/components/workflow/nodes/types';


import type { CSSProperties as BrandCSSProperties } from 'react';
// Vector brand artwork from https://www.postman.com/
const OfficialBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <img src="/icons/postman-brand-vector.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const PostmanNode: NodeDefinition = {
    type: 'automation-postman',
    label: 'Postman',
    description: 'Collections, workspaces, APIs, mocks, and monitors; trigger on mock calls and collection forks',
    category: 'developer-tools',
    Icon: OfficialBrandIcon,
    iconColor: 'text-orange-500',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => (
        <AutomationNode {...props} Icon={OfficialBrandIcon} iconColor="text-orange-500" />
    )),
};
