import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const HyperbrowserIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/hyperbrowser.svg" dark="/icons/hyperbrowser-dark.svg" className={className} style={style} />
);

export const HyperbrowserNode: NodeDefinition = {
    type: 'automation-hyperbrowser', category: 'developer-tools', label: 'Hyperbrowser',
    description: 'Automate cloud browsers, profiles, scraping, crawling, extraction and AI browser tasks',
    Icon: HyperbrowserIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={HyperbrowserIcon} iconColor="" />),
};
