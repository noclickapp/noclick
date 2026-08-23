// React-specific hooks for @noclick/sdk.
// The explicit '@noclick/sdk/react' entry is available for React-only imports;
// the root entry also re-exports this hook for existing custom components.

import { useState, useEffect } from 'react';
import { currentInputs, listeners } from './inputs.js';

type InputData = Record<string, unknown>;

/** React hook: returns reactive inputs that re-render when upstream data changes. */
export function useInputs(): InputData {
  const [inputs, setInputs] = useState<InputData>(currentInputs);

  useEffect(() => {
    const handler = (data: InputData) => setInputs(data);
    listeners.add(handler);
    setInputs(currentInputs);
    return () => { listeners.delete(handler); };
  }, []);

  return inputs;
}

// Re-export the framework-agnostic version for convenience
export { onInputsChanged } from './inputs.js';
