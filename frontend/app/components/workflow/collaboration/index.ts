/**
 * Collaboration components for workflow canvas.
 * Provides UI for collaborative editing: avatars, cursors, and selection highlighting.
 */

export { CollaboratorAvatars } from './CollaboratorAvatars';
export { CollaborativeCursors } from './CollaborativeCursors';
export {
  CollaboratorCursorNode,
  CURSOR_NODE_PREFIX,
  isCursorNode,
} from './CollaboratorCursorNode';
export {
  CollaborativeProvider,
  useCollaborativeNodeSelection,
  useCollaborativeNodeBorderColor,
} from './CollaborativeContext';
