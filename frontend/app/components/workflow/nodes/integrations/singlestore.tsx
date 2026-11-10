// SingleStore organization, project, cluster and Stage node for native workflows.
// Uses the exact official SVG linked from SingleStore's documentation.
import { forwardRef, memo } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


import type { CSSProperties as BrandCSSProperties } from 'react';
// Vector brand artwork from https://www.singlestore.com/
const OfficialBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <img src="/icons/singlestore-brand-vector.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as BrandCSSProperties} />
);

const SingleStoreIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/singlestore.svg" alt="" className={className}
            style={{ background: '#ffffff', padding: 4, borderRadius: 4, ...style }} {...props} />
    )
);
SingleStoreIcon.displayName = 'SingleStoreIcon';

export const SingleStoreNode: NodeDefinition = {
    type: 'automation-singlestore',
    label: 'SingleStore',
    description: 'Organization, project, cluster status and Stage metadata',
    category: 'databases-storage',
    keywords: ['SingleStore', 'Helios', 'workspace', 'cluster', 'project', 'Stage', 'metadata'],
    Icon: OfficialBrandIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 56 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={OfficialBrandIcon} iconColor="" />),
};

