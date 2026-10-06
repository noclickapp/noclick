// SingleStore organization, project, cluster and Stage node for native workflows.
// Uses the exact official SVG linked from SingleStore's documentation.
import { forwardRef, memo } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import type { NodeDefinition, SvgIconComponent } from './types';

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
    keywords: ['SingleStore', 'Helios', 'workspace', 'cluster', 'project', 'Stage', 'metadata'],
    Icon: SingleStoreIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 56 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={SingleStoreIcon} iconColor="" />),
};

