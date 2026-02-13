// Verify bidirectional sync: interface tab ↔ canvas node data.
// Also verify values survive tab switching with derived blocks (no local copy).

import { nc } from '~/lib/nc';

export default async function () {
  // 1. Go to Interface, add an email to the list
  nc.ui.clickTab('Interface');
  await nc.wait.ms(500);

  const addInput = document.querySelector('input[placeholder="Enter recipient email addresses"]') as HTMLInputElement;
  if (!addInput) return { error: 'Email add input not found' };

  // Type and submit
  nc.dom.type(addInput, 'test@example.com');
  await nc.wait.ms(100);
  nc.dom.pressKey(addInput, 'Enter');
  await nc.wait.ms(300);

  // Check node data updated
  const emailNode = nc.nodes.list().find(
    (n: any) => n.type === 'interface-config-form' && String(n.data?.label || '').includes('Target')
  ) as any;
  const valuesAfterAdd = JSON.parse(JSON.stringify(emailNode?.data?.values || {}));

  // 2. Switch to Canvas and back — verify persistence
  nc.ui.clickTab('Canvas');
  await nc.wait.ms(300);
  nc.ui.clickTab('Interface');
  await nc.wait.ms(500);

  // Check node data still correct
  const emailNodeAfter = nc.nodes.list().find(
    (n: any) => n.type === 'interface-config-form' && String(n.data?.label || '').includes('Target')
  ) as any;
  const valuesAfterSwitch = JSON.parse(JSON.stringify(emailNodeAfter?.data?.values || {}));

  // Check DOM renders the item
  const addInputAfter = document.querySelector('input[placeholder="Enter recipient email addresses"]') as HTMLInputElement;
  const container = addInputAfter?.closest('.space-y-1\\.5');
  const listItems = container
    ? Array.from(container.querySelectorAll('input:not([placeholder])')).map((i: any) => i.value)
    : [];

  return {
    valuesAfterAdd,
    valuesAfterSwitch,
    persistedAcrossTabSwitch: JSON.stringify(valuesAfterAdd) === JSON.stringify(valuesAfterSwitch),
    renderedItems: listItems,
    emailAdded: valuesAfterAdd.recipient_email?.includes('test@example.com'),
  };
}
