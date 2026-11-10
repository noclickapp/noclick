import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


const AppCenterIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/appcenter.png" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
AppCenterIcon.displayName = 'AppCenterIcon';

// Publisher favicon; provenance is recorded beside the asset.
export const AppCenterNode: NodeDefinition = {
    type: 'automation-appcenter',
    label: 'App Center Client',
    description: 'Legacy App Center apps, releases, distribution groups and crash diagnostics (service retired)',
    category: 'developer-tools',
    Icon: AppCenterIcon,
    keywords: ['App Center', 'Visual Studio', 'Microsoft', 'crashes', 'releases'],
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={AppCenterIcon} iconColor="" />),
};
