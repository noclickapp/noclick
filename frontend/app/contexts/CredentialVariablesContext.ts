// React context for sharing credential variables (from set-variable nodes) down the tree.
// Used to pass credential variable data from FlowCanvas into the interface tab (WorkflowInterface)
// without prop-drilling through WorkflowInterface → BlockRenderer → FieldRenderer.

import { createContext, useContext } from 'react';
import type { CredentialVariable } from '~/hooks/useCredentialVariables';

export const CredentialVariablesContext = createContext<CredentialVariable[]>([]);

export function useCredentialVariablesContext(): CredentialVariable[] {
    return useContext(CredentialVariablesContext);
}
