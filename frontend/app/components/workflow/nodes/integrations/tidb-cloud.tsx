// TiDB Cloud's catalog and canvas definition uses the official console icon.
// The backend-generated schema provides the operation and credential forms.
import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const TiDBCloudIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/tidb-cloud.svg" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
TiDBCloudIcon.displayName = 'TiDBCloudIcon';

export const TiDBCloudNode: NodeDefinition = {
    type: 'automation-tidb-cloud',
    label: 'TiDB Cloud',
    description: 'Manage Starter and Essential clusters, branches, backups and data tasks',
    category: 'databases-storage',
    keywords: ['tidb', 'pingcap', 'database', 'serverless'],
    Icon: TiDBCloudIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={TiDBCloudIcon} iconColor="" />),
};
