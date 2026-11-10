import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const FunTranslationsIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/funtranslations.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const FunTranslationsNode: NodeDefinition = {
    type: 'automation-funtranslations', category: 'content-research', label: 'FunTranslations',
    description: 'Translate text to Yoda, Pirate, Shakespeare, Morse, Braille and other styles',
    keywords: ['translation', 'fun translations', 'yoda', 'pirate', 'morse', 'braille'],
    Icon: FunTranslationsIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={FunTranslationsIcon} iconColor="" />),
};
