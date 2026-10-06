// Prepared Mindbody FlowCanvas readback for root-owned QA only.
// It inspects an existing disposable node and does not run the workflow or provider.
// Missing setup is skipped and cannot count as a passing visual capture.
import { nc } from '~/lib/nc';

export default async function () {
  const node = nc.nodes.list().find((item) => item.type === 'automation-mindbody' && item.data?.label === 'nc-qa-Mindbody');
  if (!node) return { skipped: 'Root must open the disposable nc-qa-Mindbody node.' };
  nc.nodes.select(node.id);
  await nc.wait.until(() => document.querySelector(`[data-id="${node.id}"] img[src="/icons/mindbody.svg"]`) !== null);
  const image = document.querySelector<HTMLImageElement>(`[data-id="${node.id}"] img[src="/icons/mindbody.svg"]`)!;
  await nc.wait.until(() => image.complete && image.naturalWidth > 0);
  const rect = image.getBoundingClientRect();
  nc.assert.truthy(rect.width > 0 && rect.height > 0, 'The complete official wordmark is visible');
  const current = nc.nodes.list().find((item) => item.id === node.id);
  nc.assert.truthy(current?.data.config, 'Config stays nested');
  nc.assert.equal(current?.data.config.test, true, 'Validation mode is retained');
  nc.assert.equal(current?.data.config.active, false, 'Inactive state stays false');
  nc.assert.equal(current?.data.config.promotional_emails, false, 'False preference stays false');
  nc.assert.truthy(!Object.hasOwn(current?.data ?? {}, 'promotional_emails'), 'Preference is not flattened');
  return { nodeId: node.id, inspected: true, providerRequestMade: false, captureRequired: true };
}
