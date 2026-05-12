import { memo } from 'react';
import type { BlockComponentProps } from './types';
import { FormBlock } from './blocks/FormBlock';
import { ImageBlock } from './blocks/ImageBlock';
import { AudioBlock } from './blocks/AudioBlock';
import { VideoBlock } from './blocks/VideoBlock';
import { FileBlock } from './blocks/FileBlock';
import { DataframeBlock } from './blocks/DataframeBlock';
import { HtmlReactBlock } from './blocks/HtmlReactBlock';
import { FileUploadBlock } from './blocks/FileUploadBlock';
import { ConfigFormBlock } from './blocks/ConfigFormBlock';
import { GenericBlock } from './blocks/GenericBlock';

const BLOCK_COMPONENTS: Record<string, React.ComponentType<BlockComponentProps>> = {
  form: FormBlock,
  'config-form': ConfigFormBlock,
  image: ImageBlock,
  audio: AudioBlock,
  video: VideoBlock,
  file: FileBlock,
  dataframe: DataframeBlock,
  'html-react': HtmlReactBlock,
  'file-upload': FileUploadBlock,
};

interface BlockRendererProps extends BlockComponentProps {
  blockType: string;
}

export const BlockRenderer = memo(function BlockRenderer({ blockType, ...props }: BlockRendererProps) {
  const Component = BLOCK_COMPONENTS[blockType] || GenericBlock;
  return <Component {...props} />;
});
