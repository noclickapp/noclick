// Framework-agnostic input subscription.
// React-specific useInputs() hook is in react.ts.

import { subscribe } from './core/transport.js';

type InputData = Record<string, unknown>;
type InputHandler = (inputs: InputData) => void;

export let currentInputs: InputData = {};
export const listeners = new Set<InputHandler>();

// Listen for input updates from host
subscribe('inputs:changed', (data: unknown) => {
  currentInputs = data as InputData;
  listeners.forEach(fn => fn(currentInputs));
});

/** Callback: subscribe to input changes. Returns unsubscribe function. */
export function onInputsChanged(handler: InputHandler): () => void {
  listeners.add(handler);
  return () => listeners.delete(handler);
}
