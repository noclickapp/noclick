import { memo } from 'react';
import type { CSSProperties } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition } from '~/components/workflow/nodes/types';

const ZohoWorkDriveIcon = ({
    className,
    style,
}: {
    className?: string;
    style?: CSSProperties;
}) => (
    <img
        src="/icons/zoho-work-drive.svg"
        alt=""
        aria-hidden="true"
        className={className}
        style={{ ...style, objectFit: 'contain' }}
    />
);

const ZohoWorkDriveNodeComponent = (props: NodeProps) => (
    <AutomationNode {...props} Icon={ZohoWorkDriveIcon} iconColor="" />
);

export const ZohoWorkDriveNode: NodeDefinition = {
    type: 'automation-zoho-work-drive',
    label: 'Zoho WorkDrive',
    description: 'Manage files, folders, comments and share links; watch for new or updated files',
    category: 'databases-storage',
    Icon: ZohoWorkDriveIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo(ZohoWorkDriveNodeComponent),
};
