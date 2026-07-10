// Verifies the agent-chat Share button + AgentShareDialog: button visible in
// the fullscreen agent interface, dialog mints a /a/{id} capability URL via
// agent_share:get_or_create, and the active toggle is present. Run in a dev
// editor tab with an agent-interface workflow open.

import { nc } from '~/lib/nc';

export default async function () {
  // The share button renders in both header states of AgentChatBlock.
  await nc.wait.forElement('[data-testid="agent-chat-share-button"]');
  const shareBtn = document.querySelector('[data-testid="agent-chat-share-button"]') as HTMLElement;
  nc.assert.ok(!!shareBtn, 'Share button should be visible in the agent interface');

  shareBtn.click();
  await nc.wait.forElement('[data-testid="agent-share-dialog"]');

  // get_or_create round-trips over the socket; wait for the URL input.
  await nc.wait.forElement('[data-testid="agent-share-url"]', 10000);
  const urlInput = document.querySelector('[data-testid="agent-share-url"]') as HTMLInputElement;
  const url = urlInput?.value ?? '';
  nc.assert.ok(
    /\/a\/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(url),
    `Share URL should be /a/{uuid}, got: ${url}`,
  );

  const toggle = document.querySelector('[data-testid="agent-share-active-toggle"]');
  nc.assert.ok(!!toggle, 'Active toggle should render');
  const rotate = document.querySelector('[data-testid="agent-share-rotate"]');
  nc.assert.ok(!!rotate, 'Reset link button should render');

  // Close the dialog (Escape) so the test leaves the UI clean.
  document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));

  return { url };
}
