// Custom component documents always run in an opaque-origin iframe so author code
// cannot read the host DOM, cookies, storage, or authenticated globals. Read-only
// surfaces get the smallest sandbox; the editor keeps only user-activated navigation.

export const READ_ONLY_COMPONENT_SANDBOX = 'allow-scripts';

export const EDITOR_COMPONENT_SANDBOX = [
  'allow-scripts',
  'allow-popups',
  'allow-popups-to-escape-sandbox',
  'allow-top-navigation-by-user-activation',
].join(' ');

export function componentSandbox(readOnly: boolean): string {
  return readOnly ? READ_ONLY_COMPONENT_SANDBOX : EDITOR_COMPONENT_SANDBOX;
}
