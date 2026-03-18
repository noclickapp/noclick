import { memo } from 'react';
import type { BlockComponentProps } from './types';
import { FormBlock } from './blocks/FormBlock';
import { MarkdownBlock } from './blocks/MarkdownBlock';
import { ImageBlock } from './blocks/ImageBlock';
import { AudioBlock } from './blocks/AudioBlock';
import { VideoBlock } from './blocks/VideoBlock';
import { FileBlock } from './blocks/FileBlock';
import { DataframeBlock } from './blocks/DataframeBlock';
import { PlotBlock } from './blocks/PlotBlock';
import { HtmlBlock } from './blocks/HtmlBlock';
import { FileUploadBlock } from './blocks/FileUploadBlock';
import { ChatbotBlock } from './blocks/ChatbotBlock';
import { ConfigFormBlock } from './blocks/ConfigFormBlock';
import { CustomComponentBlock } from './blocks/CustomComponentBlock';
import { GenericBlock } from './blocks/GenericBlock';

const BLOCK_COMPONENTS: Record<string, React.ComponentType<BlockComponentProps>> = {
  form: FormBlock,
  'config-form': ConfigFormBlock,
  markdown: MarkdownBlock,
  image: ImageBlock,
  audio: AudioBlock,
  video: VideoBlock,
  file: FileBlock,
  dataframe: DataframeBlock,
  plot: PlotBlock,
  html: HtmlBlock,
  'file-upload': FileUploadBlock,
  chatbot: ChatbotBlock,
  'custom-component': CustomComponentBlock,
};

interface BlockRendererProps extends BlockComponentProps {
  blockType: string;
}

export const BlockRenderer = memo(function BlockRenderer({ blockType, ...props }: BlockRendererProps) {
  const Component = BLOCK_COMPONENTS[blockType] || GenericBlock;
  return <Component {...props} />;
});
