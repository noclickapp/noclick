// Widget-specific BlockRenderer that renders all interface blocks except
// HtmlBlock and FileBlock, which use <iframe> and would require frameDomains CSP.
// This is aliased in place of ~/components/interface/BlockRenderer during the widget build.

import { memo, createElement } from 'react';
import type { BlockComponentProps } from '~/components/interface/types';
import { FormBlock } from '~/components/interface/blocks/FormBlock';
import { ImageBlock } from '~/components/interface/blocks/ImageBlock';
import { AudioBlock } from '~/components/interface/blocks/AudioBlock';
import { VideoBlock } from '~/components/interface/blocks/VideoBlock';
import { DataframeBlock } from '~/components/interface/blocks/DataframeBlock';
import { FileUploadBlock } from '~/components/interface/blocks/FileUploadBlock';
import { ChatbotBlock } from '~/components/interface/blocks/ChatbotBlock';
import { ConfigFormBlock } from '~/components/interface/blocks/ConfigFormBlock';
import { GenericBlock } from '~/components/interface/blocks/GenericBlock';

const BLOCK_COMPONENTS: Record<string, React.ComponentType<BlockComponentProps>> = {
    form: FormBlock,
    'config-form': ConfigFormBlock,
    image: ImageBlock,
    audio: AudioBlock,
    video: VideoBlock,
    dataframe: DataframeBlock,
    'file-upload': FileUploadBlock,
    chatbot: ChatbotBlock,
};

interface BlockRendererProps extends BlockComponentProps {
    blockType: string;
}

export const BlockRenderer = memo(function BlockRenderer({ blockType, ...props }: BlockRendererProps) {
    const Component = BLOCK_COMPONENTS[blockType];
    if (Component) return createElement(Component, props);
    // For iframe-dependent blocks (html, file/pdf), show a placeholder
    return createElement(GenericBlock, props);
});
