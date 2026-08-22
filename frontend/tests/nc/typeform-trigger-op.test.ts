// Verifies the Typeform `on_new_form_response` trigger operation reaches the
// frontend with the `x-is-trigger` flag set — the exact signal the
// OperationPicker uses to render an op under the amber "Triggers" section
// (see NodeConfig.tsx getOptionIsTrigger / OperationPicker.tsx).
//
// This runs in the browser against the bundled schema artifact, so it proves
// the generated typeform.json the frontend actually ships is correct.
//
// Run: mcp__nc__nc_run_test({ file: "tests/nc/typeform-trigger-op.test.ts" })

import { nc } from '~/lib/nc';
import typeformSchema from '~/schemas/nodes/typeform.json';

export default async function () {
    const schema = typeformSchema as any;
    const config = schema.properties?.config;
    nc.assert.truthy(config?.oneOf, 'typeform config schema should have oneOf variants');

    const defs = schema.$defs ?? {};
    const variants = config.oneOf.map((v: any) => {
        const name = String(v.$ref ?? '').split('/').pop();
        return name ? defs[name] ?? v : v;
    });

    // Replicate the picker's trigger detection: read `x-is-trigger` off each
    // variant's `operation` discriminator field.
    const triggerOps = variants
        .filter((v: any) => v?.properties?.operation?.['x-is-trigger'] === true)
        .map((v: any) => v.properties.operation.const);

    nc.assert.includes(
        triggerOps,
        'on_new_form_response',
        'on_new_form_response should be flagged x-is-trigger',
    );

    // The discriminator must map the trigger op so the picker can resolve it.
    const mapping = config.discriminator?.mapping ?? {};
    nc.assert.truthy(
        mapping['on_new_form_response'],
        'discriminator mapping should include the trigger op',
    );

    return { triggerOps, totalVariants: variants.length };
}
