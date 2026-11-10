import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const OsvIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/osv.svg" dark="/icons/osv-dark.svg" className={className} style={style} />
);

export const OsvNode: NodeDefinition = {
    type: 'automation-osv', category: 'developer-tools', label: 'OSV',
    description: 'Query open-source vulnerabilities, Git commits and package versions',
    keywords: ['security', 'CVE', 'OSV.dev', 'vulnerability', 'dependencies'], Icon: OsvIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={OsvIcon} iconColor="" />),
};
