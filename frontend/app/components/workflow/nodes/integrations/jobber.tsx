import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';
import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';

const JobberIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/jobber.svg" dark="/icons/jobber-dark.svg" className={className} style={style} />
);

export const JobberNode: NodeDefinition = {
    type: 'automation-jobber',
    category: 'industry',
    label: 'Jobber',
    description: 'Manage clients, jobs, quotes and custom fields in Jobber',
    Icon: JobberIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => (
        <AutomationNode {...props} Icon={JobberIcon} iconColor="" />
    )),
};
