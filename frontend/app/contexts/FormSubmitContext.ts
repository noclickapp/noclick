// React context for sharing the form submit handler from FlowCanvas into canvas nodes.
// Allows the interface-form node on the canvas to trigger workflow execution on submit.

import { createContext, useContext } from 'react';

export type FormSubmitHandler = (formNodeId: string, values: Record<string, unknown>) => void;

export const FormSubmitContext = createContext<FormSubmitHandler | null>(null);

export function useFormSubmit(): FormSubmitHandler | null {
    return useContext(FormSubmitContext);
}
