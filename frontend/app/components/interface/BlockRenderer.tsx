import { memo } from 'react';
import type { BlockComponentProps } from './types';
import { FormBlock } from './blocks/FormBlock';
import { FileBlock } from './blocks/FileBlock';
import { DataframeBlock } from './blocks/DataframeBlock';
import { HtmlReactBlock } from './blocks/HtmlReactBlock';
import { FileUploadBlock } from './blocks/FileUploadBlock';
import { GenericBlock } from './blocks/GenericBlock';
import { AgentChatBlock } from './blocks/AgentChatBlock';

const BLOCK_COMPONENTS: Record<string, React.ComponentType<BlockComponentProps>> = {
  form: FormBlock,
  file: FileBlock,
  dataframe: DataframeBlock,
  'html-react': HtmlReactBlock,
  'file-upload': FileUploadBlock,
  'agent-chat': AgentChatBlock,
};

interface BlockRendererProps extends BlockComponentProps {
  blockType: string;
}

export const BlockRenderer = memo(function BlockRenderer({ blockType, ...props }: BlockRendererProps) {
  const Component = BLOCK_COMPONENTS[blockType] || GenericBlock;
  return <Component {...props} />;
});
