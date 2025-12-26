/**
 * Context for collaborative presence state.
 * Provides node selection information to descendant components without prop drilling.
 * Nodes can use useCollaborativeNodeSelection to check if they're selected by collaborators.
 */

import { createContext, useContext, useMemo, ReactNode } from 'react';
import type { Collaborator } from '~/lib/collaboration';

interface CollaborativeContextValue {
  /** Map of nodeId -> collaborators who have selected that node */
  nodeSelections: Map<string, Collaborator[]>;
  /** All collaborators for reference */
  collaborators: Collaborator[];
}

const CollaborativeContext = createContext<CollaborativeContextValue>({
  nodeSelections: new Map(),
  collaborators: [],
});

interface CollaborativeProviderProps {
  children: ReactNode;
  nodeSelections: Map<string, Collaborator[]>;
  collaborators: Collaborator[];
}

export function CollaborativeProvider({
  children,
  nodeSelections,
  collaborators,
}: CollaborativeProviderProps) {
  const value = useMemo(
    () => ({ nodeSelections, collaborators }),
    [nodeSelections, collaborators]
  );

  return (
    <CollaborativeContext.Provider value={value}>
      {children}
    </CollaborativeContext.Provider>
  );
}

/**
 * Hook to check if a specific node is selected by any collaborator.
 * Returns the list of collaborators who have the node selected, or empty array if none.
 */
export function useCollaborativeNodeSelection(nodeId: string): Collaborator[] {
  const { nodeSelections } = useContext(CollaborativeContext);
  return nodeSelections.get(nodeId) || [];
}

/**
 * Hook to get the primary selection border color for a node.
 * Returns the color of the first collaborator selecting this node, or null if unselected.
 */
export function useCollaborativeNodeBorderColor(nodeId: string): string | null {
  const selectors = useCollaborativeNodeSelection(nodeId);
  return selectors.length > 0 ? selectors[0].color : null;
}
