// Debian Code Search exposes source matches and per-package search results.
// This definition makes the API node discoverable in the canvas and integration catalog.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const CodesearchIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/codesearch.svg" className={className} style={style} />
);

export const CodesearchNode: NodeDefinition = {
    type: 'automation-codesearch', category: 'developer-tools', label: 'Debian Code Search',
    description: 'Search Debian source code with literal text or regular expressions, optionally grouped by package',
    keywords: ['debian', 'codesearch', 'source code', 'RE2', 'packages'],
    Icon: CodesearchIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={CodesearchIcon} iconColor="" />),
};
