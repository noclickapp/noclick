import { memo, type CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const TelematicsSDKIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <>
        <img src="/icons/telematicssdk.svg" alt="" className={`${className ?? ''} dark:hidden`} style={style} />
        <img src="/icons/telematicssdk-dark.svg" alt="" className={`${className ?? ''} hidden dark:block`} style={style} />
    </>
);
export const TelematicsSDKNode: NodeDefinition = {
    type: 'automation-telematicssdk', category: 'industry', label: 'Telematics SDK',
    description: 'Manage Damoov users, instances and SDK settings, and watch for new users.',
    keywords: ['Damoov', 'telematics', 'driving', 'fleet', 'Quick start'],
    Icon: TelematicsSDKIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={TelematicsSDKIcon} iconColor="" />),
};
