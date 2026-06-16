// @vitest-environment jsdom
import { afterEach, describe, expect, it } from 'vitest';
import { act, createElement } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { useInputs } from '../src/react';
import { setTransport } from '../src/core/transport';
import { createFakeHost } from './helpers/fakeHost';

(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;

describe('useInputs', () => {
  let root: Root | null = null;
  let container: HTMLDivElement | null = null;

  afterEach(() => {
    if (root) act(() => root!.unmount());
    container?.remove();
    root = null;
    container = null;
  });

  it('re-renders the component when the host pushes inputs:changed', () => {
    const host = createFakeHost();
    setTransport(host.transport);

    container = document.createElement('div');
    document.body.appendChild(container);

    function Probe() {
      const inputs = useInputs();
      return createElement('span', { id: 'out' }, JSON.stringify(inputs));
    }

    root = createRoot(container);
    act(() => root!.render(createElement(Probe)));
    const text = () => container!.querySelector('#out')!.textContent;

    act(() => host.emitEvent('inputs:changed', { name: 'ada' }));
    expect(text()).toBe(JSON.stringify({ name: 'ada' }));

    act(() => host.emitEvent('inputs:changed', { name: 'lovelace', n: 2 }));
    expect(text()).toBe(JSON.stringify({ name: 'lovelace', n: 2 }));
  });
});
