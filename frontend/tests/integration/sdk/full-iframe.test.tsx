// L3 full E2E: the real shipped @noclick/sdk bundle runs in an opaque-origin,
// sandboxed iframe and talks to the real useSDKBridge exclusively over postMessage.
// The host never reaches into author-controlled window or document state.
//
// Covers the three named scenarios against the real component path:
//   (a) restored output  — nodes.getOutput reads a hydrated node.data.output
//   (b) realtime         — node:output push reaches the component
//   (c) execute and wait — runNodesAndGetOutput resolves when targets complete
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useRef } from 'react';
import { render, act } from '@testing-library/react';
import type { Node } from '@xyflow/react';
import { useSDKBridge } from '~/hooks/useSDKBridge';
import { componentSandbox } from '~/lib/componentSandbox';
import { installMockSocket, type MockSocket } from '../helpers/mockSocket';
// The real published bundle — exactly what npm ships and components import.
import sdkBundle from '../../../../sdk/typescript/dist/sdk.esm.js?raw';

let socket: MockSocket;
let teardown: () => void;
let unmount: (() => void) | null = null;
let frameMessages: MessageEvent[] = [];
let captureFrameMessage: ((event: MessageEvent) => void) | null = null;
let commandCounter = 0;

beforeEach(() => {
  ({ socket, teardown } = installMockSocket());
  // The bridge's init effect fetches node outputs on load to seed useInputs;
  // give it a default reply so it never hangs. Specific tests override this.
  socket.replyTo('workflow:get_node_outputs', { outputs: {} });
  frameMessages = [];
  captureFrameMessage = (event) => frameMessages.push(event);
  window.addEventListener('message', captureFrameMessage);
});
afterEach(() => {
  if (unmount) act(() => unmount!());
  unmount = null;
  if (captureFrameMessage) window.removeEventListener('message', captureFrameMessage);
  captureFrameMessage = null;
  teardown?.();
});

// The real bundle statically imports `react` (for useInputs), which the build
// externalizes. Our vanilla component never calls useInputs, so a stub that just
// satisfies the named binding is enough — no esm.sh / network needed.
const REACT_STUB = 'export const useState = (v) => [v, () => {}];\nexport const useEffect = () => {};\nexport default {};';

function jsDataUri(src: string): string {
  return 'data:text/javascript;base64,' + btoa(unescape(encodeURIComponent(src)));
}

/** Build a srcdoc that imports the real SDK via a data-URI import-map. Test
 * commands and results cross the same postMessage-only boundary as the SDK. */
function buildSrcdoc(): string {
  const importmap = JSON.stringify({
    imports: { '@noclick/sdk': jsDataUri(sdkBundle), react: jsDataUri(REACT_STUB) },
  });
  return `<!doctype html><html><head><meta charset="utf-8">
<script>
const reportFrameError = (error) => parent.postMessage({ type: 'sdk-e2e:error', error: String(error) }, '*');
window.addEventListener('error', event => reportFrameError(event.message || event.error));
window.addEventListener('unhandledrejection', event => reportFrameError('rej:' + String(event.reason)));
</script>
<script type="importmap">${importmap}</script>
</head><body><div id="out">init</div>
<script type="module">
  import { nodes, execution, workflow, onInputsChanged } from '@noclick/sdk';
  const out = document.getElementById('out');
  let lastOutput = null;
  let lastInputs = {};

  execution.onNodeOutput('gen', (output) => {
    lastOutput = output;
    out.textContent = 'live:' + JSON.stringify(output);
  });
  onInputsChanged((inputs) => { lastInputs = inputs; });

  window.addEventListener('message', async (event) => {
    if (event.source !== parent) return;
    const message = event.data;
    if (!message || message.type !== 'sdk-e2e:command') return;

    try {
      let result;
      switch (message.command) {
        case 'getOutput':
          result = await nodes.getOutput(message.args.nodeId);
          out.textContent = 'output:' + JSON.stringify(result);
          break;
        case 'run':
          out.textContent = 'running';
          result = await execution.runNodesAndGetOutput(message.args.runNodes, message.args.targets).all();
          out.textContent = 'done:' + JSON.stringify(result);
          break;
        case 'getLastOutput': result = lastOutput; break;
        case 'getInputs': result = lastInputs; break;
        case 'getInfo': result = await workflow.getInfo(); break;
        case 'getNodeId': result = workflow.nodeId; break;
        default: throw new Error('Unknown test command: ' + message.command);
      }
      parent.postMessage({ type: 'sdk-e2e:result', id: message.id, result, text: out.textContent }, '*');
    } catch (error) {
      parent.postMessage({
        type: 'sdk-e2e:result',
        id: message.id,
        error: error instanceof Error ? error.message : String(error),
        text: out.textContent,
      }, '*');
    }
  });
  parent.postMessage({ type: 'sdk-e2e:ready' }, '*');
</script></body></html>`;
}

function Host({ nodes, workflowId, edges = [] }: { nodes: Node[]; workflowId: string; edges?: Array<{ source: string; target: string }> }) {
  const iframeRef = useRef<HTMLIFrameElement>(null);
  useSDKBridge({ iframeRef, nodeId: 'component-1', workflowId, getNodes: () => nodes, getEdges: () => edges, updateNodeData: () => {} });
  return (
    <iframe
      ref={iframeRef}
      title="sdk-e2e"
      srcDoc={buildSrcdoc()}
      sandbox={componentSandbox(false)}
      style={{ width: 400, height: 200 }}
    />
  );
}

function fromFrame(iframe: HTMLIFrameElement, event: MessageEvent): boolean {
  return event.source === iframe.contentWindow;
}

async function mountHost(nodes: Node[], workflowId = 'wf-1', edges: Array<{ source: string; target: string }> = []) {
  let container!: HTMLElement;
  act(() => {
    const rendered = render(<Host nodes={nodes} workflowId={workflowId} edges={edges} />);
    container = rendered.container;
    unmount = rendered.unmount;
  });
  const iframe = container.querySelector('iframe') as HTMLIFrameElement;
  await vi.waitFor(() => {
    const failure = frameMessages.find((event) => fromFrame(iframe, event) && event.data?.type === 'sdk-e2e:error');
    if (failure) throw new Error('iframe SDK error: ' + failure.data.error);
    expect(frameMessages.some((event) => fromFrame(iframe, event) && event.data?.type === 'sdk-e2e:ready')).toBe(true);
  }, { timeout: 10000 });
  return iframe;
}

async function frameCommand(
  iframe: HTMLIFrameElement,
  command: string,
  args: Record<string, unknown> = {},
): Promise<{ result: unknown; text: string }> {
  const id = `command-${++commandCounter}`;
  iframe.contentWindow!.postMessage({ type: 'sdk-e2e:command', id, command, args }, '*');
  await vi.waitFor(() => {
    const failure = frameMessages.find((event) => fromFrame(iframe, event) && event.data?.type === 'sdk-e2e:error');
    if (failure) throw new Error('iframe SDK error: ' + failure.data.error);
    expect(frameMessages.some(
      (event) => fromFrame(iframe, event) && event.data?.type === 'sdk-e2e:result' && event.data.id === id,
    )).toBe(true);
  });
  const message = frameMessages.find(
    (event) => fromFrame(iframe, event) && event.data?.type === 'sdk-e2e:result' && event.data.id === id,
  )!.data;
  if (message.error) throw new Error(message.error);
  return { result: message.result, text: message.text };
}

const node = (id: string, data: Record<string, unknown>): Node =>
  ({ id, type: 'automation-http-request', position: { x: 0, y: 0 }, data } as unknown as Node);

describe('SDK E2E (opaque iframe + real bundle)', () => {
  it('(a) restored output: getOutput reads hydrated node.data.output across the boundary', async () => {
    const iframe = await mountHost([node('data-1', { output: { hello: 'world' } })]);
    const { result, text } = await frameCommand(iframe, 'getOutput', { nodeId: 'data-1' });
    expect(result).toEqual({ hello: 'world' });
    expect(text).toBe('output:{"hello":"world"}');
  });

  it('(a-race) getOutput fetches the restored output when the canvas has not hydrated it yet', async () => {
    // Reproduces the initial-load race: the component mounts and reads getOutput
    // before node.data.output is hydrated. The bridge must fetch from the backend.
    socket.replyTo('workflow:get_node_outputs', { outputs: { 'data-1': { hello: 'late' } } });
    const iframe = await mountHost([node('data-1', {})]); // no in-memory output
    const { result, text } = await frameCommand(iframe, 'getOutput', { nodeId: 'data-1' });
    expect(result).toEqual({ hello: 'late' });
    expect(text).toBe('output:{"hello":"late"}');
    expect(socket.hasSent('workflow:get_node_outputs')).toBe(true);
  });

  it('(init) the component receives its nodeId via the ready handshake', async () => {
    const iframe = await mountHost([]);
    const { result } = await frameCommand(iframe, 'getNodeId');
    expect(result).toBe('component-1');
  });

  it('(getInfo) returns the real workflow name through the bridge', async () => {
    socket.replyTo('workflow:get', {
      workflow: { id: 'wf-1', name: 'Repo Dashboard', workflow_data: { nodes: [{ id: 'data-1' }] } },
    });
    const iframe = await mountHost([node('data-1', {})]);
    const { result } = await frameCommand(iframe, 'getInfo');
    expect(result).toMatchObject({ id: 'wf-1', name: 'Repo Dashboard' });
  });

  it('(inputs-init) seeds inputs from restored UPSTREAM outputs on load', async () => {
    // up1 is wired into the component; down is not → only up1 is seeded.
    socket.replyTo('workflow:get_node_outputs', { outputs: { up1: { v: 1 }, down: { v: 9 } } });
    const iframe = await mountHost(
      [node('up1', {})],
      'wf-1',
      [{ source: 'up1', target: 'component-1' }],
    );
    await vi.waitFor(async () => {
      const { result } = await frameCommand(iframe, 'getInputs');
      expect(result).toEqual({ up1: { v: 1 } });
    });
  });

  it('(b) realtime: a backend node:output reaches the component via onNodeOutput', async () => {
    const iframe = await mountHost([node('gen', {})]);
    act(() => socket.serverEmit('workflow:node:output', { workflow_id: 'wf-1', node_id: 'gen', output: { tokens: 'hi' } }));
    await vi.waitFor(async () => {
      const { result, text } = await frameCommand(iframe, 'getLastOutput');
      expect(result).toEqual({ tokens: 'hi' });
      expect(text).toBe('live:{"tokens":"hi"}');
    });
  });

  it('(c) execute and wait: runNodesAndGetOutput resolves when all targets complete', async () => {
    const iframe = await mountHost([node('gen', {})]);

    // The bridge dispatches run-from-node once it has registered the stream.
    let runFired = false;
    const onRun = () => { runFired = true; };
    document.addEventListener('noclick:run-from-node', onRun, { once: true });

    const pending = frameCommand(iframe, 'run', { runNodes: [{ id: 'gen' }], targets: ['gen'] });
    await vi.waitFor(() => expect(runFired).toBe(true));

    act(() => {
      socket.serverEmit('workflow:node:output', { workflow_id: 'wf-1', node_id: 'gen', output: { answer: 42 } });
      socket.serverEmit('workflow:node:state', { workflow_id: 'wf-1', node_id: 'gen', state: 'completed' });
    });

    const { result, text } = await pending;
    expect(result).toEqual({ gen: { answer: 42 } });
    expect(text).toBe('done:{"gen":{"answer":42}}');
    document.removeEventListener('noclick:run-from-node', onRun);
  });
});
