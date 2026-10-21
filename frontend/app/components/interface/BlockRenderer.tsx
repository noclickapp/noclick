import { lazy, memo, Suspense, type ComponentType } from 'react';
import type { BlockComponentProps } from './types';
import { GenericBlock } from './blocks/GenericBlock';

// Each block loads with the first one of its kind drawn: a table brings ag-grid, a
// chat its transcript, a component the SDK bridge. An interface node, the interface
// tab and the fork canvas draw only the blocks they hold.
const BLOCK_COMPONENTS: Record<string, ComponentType<BlockComponentProps>> = {
  form: lazy(() => import('./blocks/FormBlock').then((m) => ({ default: m.FormBlock }))),
  file: lazy(() => import('./blocks/FileBlock').then((m) => ({ default: m.FileBlock }))),
  dataframe: lazy(() => import('./blocks/DataframeBlock').then((m) => ({ default: m.DataframeBlock }))),
  'html-react': lazy(() => import('./blocks/HtmlReactBlock').then((m) => ({ default: m.HtmlReactBlock }))),
  'file-upload': lazy(() => import('./blocks/FileUploadBlock').then((m) => ({ default: m.FileUploadBlock }))),
  'agent-chat': lazy(() => import('./blocks/AgentChatBlock').then((m) => ({ default: m.AgentChatBlock }))),
};

interface BlockRendererProps extends BlockComponentProps {
  blockType: string;
}

export const BlockRenderer = memo(function BlockRenderer({ blockType, ...props }: BlockRendererProps) {
  const Component = BLOCK_COMPONENTS[blockType] || GenericBlock;
  return (
    <Suspense fallback={null}>
      <Component {...props} />
    </Suspense>
  );
});
