import { memo, type CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';
import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';

const TelematicsSDKIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/telematicssdk.svg" dark="/icons/telematicssdk-dark.svg" className={className} style={style} />
);
export const TelematicsSDKNode: NodeDefinition = {
    type: 'automation-telematicssdk', category: 'industry', label: 'Telematics SDK',
    description: 'Manage Damoov users, instances and SDK settings, and watch for new users.',
    keywords: ['Damoov', 'telematics', 'driving', 'fleet', 'Quick start'],
    Icon: TelematicsSDKIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={TelematicsSDKIcon} iconColor="" />),
};
