// How a node definition becomes its ReactFlow node type: wrapped (collaborative border + editable label) and
// memoized on the props that matter (positions change on every drag frame). Node files export RAW components;
// a definition sets `memoCompare` for its own comparison, or `skipAutoMemo` when it memoizes itself.
import { memo, type ComponentType } from 'react';
import type { NodeProps } from '@xyflow/react';
import { withNodeWrapper } from './withNodeWrapper';
import { nodePropsAreEqual, type NodeDefinition } from './types';

export function nodeTypeComponent(definition: NodeDefinition): ComponentType<NodeProps> {
    const wrapped = withNodeWrapper(definition.component);
    return definition.skipAutoMemo ? wrapped : memo(wrapped, definition.memoCompare || nodePropsAreEqual);
}
