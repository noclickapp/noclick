import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const LanguageToolIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <>
        <img src="/icons/languagetool.svg" alt="" aria-hidden="true" className={`${className ?? ''} dark:hidden`} style={style} />
        <img src="/icons/languagetool-dark.svg" alt="" aria-hidden="true" className={`${className ?? ''} hidden dark:block`} style={style} />
    </>
);

export const LanguageToolNode: NodeDefinition = {
    type: 'automation-languagetool', category: 'documents', label: 'LanguageTool',
    description: 'Check grammar, spelling and style, and manage personal dictionary words',
    keywords: ['proofreading', 'grammar', 'spelling', 'writing', 'dictionary'],
    Icon: LanguageToolIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={LanguageToolIcon} iconColor="" />),
};
