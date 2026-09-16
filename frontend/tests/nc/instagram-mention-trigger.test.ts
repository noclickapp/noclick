import { nc } from '~/lib/nc';
import { getSchemaInfo } from '~/utils/schemaFieldExtractor';
import { isTriggerSource } from '~/utils/nodeMeta';

export default async function () {
    const info = getSchemaInfo('automation-instagram');
    nc.assert.truthy(info?.hasDiscriminator, 'Instagram operation picker is available');
    const index = info!.options.findIndex((_, i) =>
        info!.discriminator.optionToValue.get(i) === 'on_mention');
    nc.assert.truthy(index >= 0, 'On Mention is offered in the picker');
    const option = info!.options[index];
    const schema = option.$ref ? info!.resolveRef(option.$ref) : option;
    nc.assert.equal(schema.properties.operation.title, 'On Mention', 'Readable label');
    nc.assert.truthy(schema.properties.operation['x-is-trigger'], 'Classified as a trigger');
    nc.assert.equal(schema.properties.subscription_status['ui:widget'], 'readonly', 'Visible status field');
    nc.assert.truthy(schema.properties.subscription_status['ui:loadValue'], 'Status activates subscription');
    nc.assert.truthy(isTriggerSource('automation-instagram', 'on_mention'), 'Available to Add Trigger');
    nc.assert.falsy(schema.properties.comment_id, 'No manual comment ID needed');
    return { operation: 'On Mention', status: 'Picker and activation metadata verified' };
}
