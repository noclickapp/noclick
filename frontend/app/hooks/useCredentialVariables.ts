// Shared hook that derives credential variables from set-variable nodes in the workflow.
// Extracts variable assignments that reference credential fields, annotating each with
// its resolved credential types so dropdowns can filter by type.

import { useMemo } from 'react';
import type { Node } from '@xyflow/react';
import { getServiceForCredentialType } from '~/utils/credentialTypes';

export interface CredentialVariable {
    name: string;
    label: string;
    credentialTypes: string[];
}

export function useCredentialVariables(nodes: Node[]): CredentialVariable[] {
    return useMemo(() => {
        const vars: CredentialVariable[] = [];
        for (const node of nodes) {
            if (node.type !== 'set-variable') continue;
            const config = (node.data as any)?.config || {};
            const assignments: any[] = Array.isArray(config.assignments) ? config.assignments : [];

            for (const a of assignments) {
                const varName = a?.variable_name;
                if (!varName) continue;

                const credentialTypes: string[] = [];
                let label = varName as string;
                const ref = typeof a.value === 'string' ? a.value.match(/^\{\{(.+)\}\}$/) : null;
                if (ref) {
                    const dotIdx = ref[1].indexOf('.');
                    if (dotIdx !== -1) {
                        const sourceNodeId = ref[1].slice(0, dotIdx);
                        // Strip "values." prefix used by interface-config-form nodes
                        const rawFieldPath = ref[1].slice(dotIdx + 1);
                        const fieldName = rawFieldPath.startsWith('values.') ? rawFieldPath.slice('values.'.length) : rawFieldPath;
                        const sourceNode = nodes.find(n => n.id === sourceNodeId);
                        const sourceConfig = (sourceNode?.data as any)?.config || {};
                        const rawFields = sourceConfig.fields;
                        const fields = typeof rawFields === 'string'
                            ? (() => { try { return JSON.parse(rawFields); } catch { return null; } })()
                            : rawFields;
                        if (Array.isArray(fields)) {
                            const field = (fields as any[]).find(f => f.name === fieldName);
                            if (field?.label) label = field.label;
                            if (field?.credential_type) {
                                const service = getServiceForCredentialType(field.credential_type);
                                credentialTypes.push(...(service?.acceptedCredentialTypes ?? [field.credential_type]));
                            }
                        }
                    }
                }

                // Only include as credential variable if it actually references a credential field
                // Deduplicate by variable name (multiple set-variable nodes may declare the same var)
                if (credentialTypes.length > 0 && !vars.some(v => v.name === varName)) {
                    vars.push({ name: varName, label, credentialTypes });
                }
            }
        }
        return vars;
    }, [nodes]);
}
