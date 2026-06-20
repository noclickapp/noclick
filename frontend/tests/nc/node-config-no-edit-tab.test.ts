// Verifies the node config panel exposes exactly two view tabs — Configuration
// and Settings — after the per-node "Edit" tab (EditPromptView) was removed for
// being confusing. Guards against the Edit tab reappearing and confirms the
// remaining two tabs still toggle. Runs against whatever workflow is open; needs
// at least one ordinary config node (not a sticky note / agent / trigger).

import { nc } from '~/lib/nc';

/** Buttons that make up the ConfigViewToggle (uppercase, tracking-wider). */
function toggleButtons(): HTMLButtonElement[] {
  return Array.from(document.querySelectorAll<HTMLButtonElement>('button')).filter(
    b => /tracking-wider/.test(b.className) && /^(Edit|Configuration|Settings)$/i.test((b.textContent || '').trim()),
  );
}

const toggleLabels = () => toggleButtons().map(b => (b.textContent || '').trim());
const activeLabel = () =>
  toggleButtons()
    .filter(b => b.className.includes('bg-white/[0.10]'))
    .map(b => (b.textContent || '').trim());
const clickTab = (name: string) =>
  toggleButtons().find(b => (b.textContent || '').trim().toLowerCase() === name.toLowerCase())?.click();

export default async function () {
  // Pick an ordinary config node — sticky notes have no config panel, agents and
  // provider-wired nodes swap the toggle for the operation allowlist.
  const node = nc.nodes
    .list()
    .find((n: any) => !['stickyNote', 'agent'].includes(n.type) && !String(n.type).startsWith('trigger-'));
  nc.assert.truthy(node, 'an ordinary config node must exist on the canvas');
  const id = node.id;

  // Self-heal against harness timing: re-dispatch selection until the toggle renders.
  await nc.wait.until(() => {
    if (toggleButtons().length) return true;
    nc.nodes.select(id);
    return false;
  }, 12000, 300);

  // The toggle must be exactly Configuration + Settings, with Configuration
  // active by default and no Edit tab anywhere.
  const labels = toggleLabels();
  nc.assert.equal(labels.length, 2, `expected 2 view tabs, got ${labels.join(', ')}`);
  nc.assert.includes(labels, 'Configuration', 'Configuration tab must be present');
  nc.assert.includes(labels, 'Settings', 'Settings tab must be present');
  nc.assert.falsy(
    labels.some(l => /^edit$/i.test(l)),
    'the Edit tab must NOT be present',
  );
  nc.assert.equal(activeLabel()[0], 'Configuration', 'Configuration is the default active view');

  // Both remaining tabs must still toggle (the ternary render survived the edit-branch removal).
  clickTab('Settings');
  await nc.wait.until(() => activeLabel()[0] === 'Settings', 4000, 150);
  nc.assert.equal(activeLabel()[0], 'Settings', 'clicking Settings switches to the Settings view');

  clickTab('Configuration');
  await nc.wait.until(() => activeLabel()[0] === 'Configuration', 4000, 150);
  nc.assert.equal(activeLabel()[0], 'Configuration', 'clicking Configuration switches back');

  return { tabs: labels, nodeId: id, nodeType: node.type };
}
