// A malicious public/template component may execute inside its sandbox, but it
// must not read host DOM/session storage or obtain a privileged SDK response.
// This browser regression verifies the real read-only HtmlReactBlock boundary.
import { afterEach, describe, expect, it, vi } from 'vitest';
import { act, render } from '@testing-library/react';
import { HtmlReactBlock } from '~/components/interface/blocks/HtmlReactBlock';

const HOST_SECRET_KEY = 'noclick-malicious-template-probe';

const MALICIOUS_HTML = `
<script>
  const probe = { parentDom: false, parentStorage: null, parentCookie: null };
  window.addEventListener('message', (event) => {
    if (event.data?.type === 'noclick:response' && event.data.id === 'malicious-config-write') {
      parent.postMessage({ type: 'malicious-response', response: event.data }, '*');
    }
  });
  try {
    probe.parentDom = Boolean(parent.document.documentElement);
  } catch (_) {}
  try {
    probe.parentStorage = parent.localStorage.getItem('${HOST_SECRET_KEY}');
  } catch (_) {}
  try {
    probe.parentCookie = parent.document.cookie;
  } catch (_) {}
  parent.postMessage({ type: 'malicious-probe', probe }, '*');
  setTimeout(() => {
    parent.postMessage({
      type: 'noclick:request',
      id: 'malicious-config-write',
      method: 'nodes.setConfig',
      params: { nodeId: 'victim-node', config: { compromised: true } },
    }, '*');
  }, 20);
  setTimeout(() => parent.postMessage({ type: 'malicious-finished' }, '*'), 100);
</script>`;

let unmount: (() => void) | null = null;

afterEach(() => {
  if (unmount) act(() => unmount!());
  unmount = null;
  localStorage.removeItem(HOST_SECRET_KEY);
});

describe('public/template custom component isolation', () => {
  it('keeps author HTML opaque and exposes no live SDK bridge', async () => {
    localStorage.setItem(HOST_SECRET_KEY, 'host-session-secret');
    const messages: MessageEvent[] = [];
    const capture = (event: MessageEvent) => messages.push(event);
    window.addEventListener('message', capture);
    const onInteraction = vi.fn();

    try {
      let container!: HTMLElement;
      act(() => {
        const rendered = render(
          <HtmlReactBlock
            id="public-component"
            config={{ operation: 'render_html_interface', content: MALICIOUS_HTML }}
            isSelected={false}
            isReadOnly
            onConfigChange={() => {}}
            onInteraction={onInteraction}
          />,
        );
        container = rendered.container;
        unmount = rendered.unmount;
      });

      const iframe = container.querySelector('iframe') as HTMLIFrameElement;
      expect(iframe).toBeTruthy();
      expect(iframe.getAttribute('sandbox')).toBe('allow-scripts');

      await vi.waitFor(() => {
        expect(messages.some(
          (event) => event.source === iframe.contentWindow && event.data?.type === 'malicious-finished',
        )).toBe(true);
      });

      const probe = messages.find(
        (event) => event.source === iframe.contentWindow && event.data?.type === 'malicious-probe',
      )?.data.probe;
      expect(probe).toEqual({ parentDom: false, parentStorage: null, parentCookie: null });

      // The read-only wrapper may offer a host-controlled fork prompt, but it never
      // mounts useSDKBridge and therefore cannot acknowledge or perform the write.
      expect(onInteraction).toHaveBeenCalled();
      expect(messages.some(
        (event) => event.source === iframe.contentWindow
          && event.data?.type === 'malicious-response',
      )).toBe(false);
    } finally {
      window.removeEventListener('message', capture);
    }
  });
});
