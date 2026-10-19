// The Python function's form refuses hardware the hosted runtime refuses at create:
// more GPUs than the type takes (A10G: 4, the rest: 8) and a timeout under 10s.
// Validated the way NodeConfig validates a node's form (AJV over the generated schema).
import Ajv2020 from 'ajv/dist/2020';
import addFormats from 'ajv-formats';
import { describe, expect, it } from 'vitest';
import schema from '~/schemas/nodes/serverless-function.json';

function pythonFormValidator() {
    const ajv = new Ajv2020({ allErrors: true, strict: false, validateFormats: true, coerceTypes: true });
    addFormats(ajv);
    const defs = (schema as any).$defs;
    return ajv.compile({ type: 'object', properties: defs.PythonRuntimeConfig.properties, $defs: defs });
}

function errorsFor(config: Record<string, unknown>) {
    const validate = pythonFormValidator();
    validate(config);
    return (validate.errors || []).map(e => `${e.instancePath} ${e.keyword} ${JSON.stringify(e.params)}`);
}

describe('serverless function hardware limits', () => {
    it('takes up to 4 A10G GPUs and up to 8 of the other types', () => {
        expect(errorsFor({ hardware: { gpu_type: 'A10G', gpu_count: 4 } })).toEqual([]);
        expect(errorsFor({ hardware: { gpu_type: 'H100', gpu_count: 8 } })).toEqual([]);
        expect(errorsFor({ hardware: { gpu_type: 'none', gpu_count: 8 } })).toEqual([]);
    });

    it('refuses more GPUs than the type takes', () => {
        expect(errorsFor({ hardware: { gpu_type: 'A10G', gpu_count: 5 } })).toContain(
            '/hardware/gpu_count maximum {"comparison":"<=","limit":4}',
        );
        expect(errorsFor({ hardware: { gpu_type: 'T4', gpu_count: 9 } })).toContain(
            '/hardware/gpu_count maximum {"comparison":"<=","limit":8}',
        );
    });

    it('refuses a timeout under 10 seconds', () => {
        expect(errorsFor({ timeout_seconds: 10 })).toEqual([]);
        expect(errorsFor({ timeout_seconds: 5 })).toContain('/timeout_seconds minimum {"comparison":">=","limit":10}');
    });
});
