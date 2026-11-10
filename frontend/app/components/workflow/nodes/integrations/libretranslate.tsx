// LibreTranslate supplies translation and language detection tools for workflows.
// This definition makes the self-registering node available in the AI catalog.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';
import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';

const LibreTranslateIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/libretranslate.svg" dark="/icons/libretranslate-dark.svg" className={className} style={{ ...style, objectFit: 'contain' }} />
);

export const LibreTranslateNode: NodeDefinition = {
    type: 'automation-libretranslate', label: 'LibreTranslate', category: 'ai',
    description: 'Translate text, HTML, batches and files; detect languages and suggest corrections',
    keywords: ['translation', 'language', 'localization'],
    Icon: LibreTranslateIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={LibreTranslateIcon} iconColor="" />),
};
