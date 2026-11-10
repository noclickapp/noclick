// Displays the CompanyCam integration in the catalog and workflow canvas.
// Configuration and credentials come from the generated backend schema.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const CompanycamIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/companycam.svg" className={className} style={style} />
);

export const CompanycamNode: NodeDefinition = {
    type: 'automation-companycam', category: 'industry', label: 'CompanyCam',
    description: 'Manage projects, photos, comments, customers and tags',
    keywords: ['companycam', 'construction', 'jobsite', 'photos'],
    Icon: CompanycamIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={CompanycamIcon} iconColor="" />),
};
