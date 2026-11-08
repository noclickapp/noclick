import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';
import type { CSSProperties as BrandCSSProperties } from 'react';
// Vector brand artwork from https://sirv.com
const OfficialBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <img src="/icons/sirv.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as BrandCSSProperties} />
);

export const SirvNode: NodeDefinition = {
    type: 'automation-sirv',
    label: 'Sirv',
    description: 'Current folder and file metadata without media downloads',
    category: 'media',
    keywords: ['files', 'folders', 'catalog', 'file size', 'approval', 'digital assets'],
    Icon: OfficialBrandIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: (props: NodeProps) => <AutomationNode {...props} Icon={OfficialBrandIcon} iconColor="" />,
};
