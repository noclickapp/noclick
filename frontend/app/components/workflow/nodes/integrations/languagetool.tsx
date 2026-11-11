import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';
import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';

const LanguageToolIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/languagetool.svg" dark="/icons/languagetool-dark.svg" className={className} style={style} />
);

export const LanguageToolNode: NodeDefinition = {
    type: 'automation-languagetool', category: 'documents', label: 'LanguageTool',
    description: 'Check grammar, spelling and style, and manage personal dictionary words',
    keywords: ['proofreading', 'grammar', 'spelling', 'writing', 'dictionary'],
    Icon: LanguageToolIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={LanguageToolIcon} iconColor="" />),
};
