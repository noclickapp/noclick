// Consolidated component block — renders HTML or JSX/React components with SDK access.
// HTML mode: renders content directly in an iframe (no transpilation).
// JSX mode: client-side Sucrase transpilation for instant preview, with IndexedDB cache.

import { useRef, useCallback, useEffect, type RefObject } from 'react';
import { Code2, Globe, Loader2 } from 'lucide-react';
import { useSDKBridge } from '~/hooks/useSDKBridge';
import { useCredentialOAuth } from '~/hooks/useCredentialOAuth';
import { useClientTranspile } from '~/hooks/useClientTranspile';
import { useWorkflowId } from '~/components/workflow/WorkflowContext';
import { componentSandbox } from '~/lib/componentSandbox';
import type { BlockComponentProps } from '../types';

// Suppress ResizeObserver loop warnings from iframe content (Tailwind CDN triggers these during resize).
if (typeof window !== 'undefined' && !(window as any).__ncResizeObserverSuppressed) {
  (window as any).__ncResizeObserverSuppressed = true;
  window.addEventListener('error', (e) => {
    if (e.message?.includes('ResizeObserver')) {
      e.stopImmediatePropagation();
      e.preventDefault();
    }
  });
}

export function HtmlReactBlock(props: BlockComponentProps) {
  // The interactive variant pulls in useCredentialOAuth (22 OAuth provider hooks → 22
  // BroadcastChannel listeners) and useSDKBridge. In read-only previews (template page
  // embeds) none of that machinery can fire, but it still costs heap + listeners on every
  // mount, which on mobile contributes to the iframe-content OOM. Split here so a read-only
  // block has zero OAuth/SDK overhead.
  if (props.isReadOnly && !props.sdkBridge) return <HtmlReactBlockReadOnly {...props} />;
  return <HtmlReactBlockInteractive {...props} />;
}

function HtmlReactBlockReadOnly({ config, output, onInteraction }: BlockComponentProps) {
  const operation = (config.operation as string) || 'render_html_interface';
  const isJsx = operation === 'render_jsx_react_interface';
  const nodeOutput = output as Record<string, unknown> | undefined;
  const backendError = nodeOutput?.error as string | undefined;
  const jsxSource = (config.jsx_source as string) || '';
  const htmlContent = (config.content as string) || '';

  const { srcdoc: clientSrcdoc, error: clientError, transpiling } = useClientTranspile(
    jsxSource,
    isJsx && !!jsxSource,
  );

  const iframeRef = useRef<HTMLIFrameElement>(null);

  // Intercept SDK requests from the inner iframe and forward them as a fork prompt.
  useEffect(() => {
    if (!onInteraction) return;
    const handleMessage = (event: MessageEvent) => {
      if (event.source !== iframeRef.current?.contentWindow) return;
      const msg = event.data;
      if (msg?.type === 'noclick:request' || msg?.type === 'noclick:fire') {
        onInteraction();
      }
    };
    window.addEventListener('message', handleMessage);
    return () => window.removeEventListener('message', handleMessage);
  }, [onInteraction]);

  return renderHtmlReactIframe({
    isJsx,
    htmlContent,
    jsxSource,
    clientSrcdoc,
    clientError,
    backendError,
    backendSrcdoc: (nodeOutput?.srcdoc as string) || '',
    transpiling,
    iframeRef,
    readOnly: true,
  });
}

function HtmlReactBlockInteractive({ id, config, output, isReadOnly, sdkBridge }: BlockComponentProps) {
  const effectiveReadOnly = !!(isReadOnly || sdkBridge?.readOnly);
  const operation = (config.operation as string) || 'render_html_interface';
  const isJsx = operation === 'render_jsx_react_interface';
  const nodeOutput = output as Record<string, unknown> | undefined;
  const backendError = nodeOutput?.error as string | undefined;
  const jsxSource = (config.jsx_source as string) || '';
  const htmlContent = (config.content as string) || '';

  const { srcdoc: clientSrcdoc, error: clientError, transpiling } = useClientTranspile(
    jsxSource,
    isJsx && !!jsxSource,
  );

  const iframeRef = useRef<HTMLIFrameElement>(null);

  const oauthCallbackRef = useRef<((credentialId: string, provider: string) => void) | null>(null);
  const oauthCancelRef = useRef<(() => void) | null>(null);
  const { connect: oauthConnect } = useCredentialOAuth({
    onCredentialCreated: (credentialId, provider) => {
      oauthCallbackRef.current?.(credentialId, provider);
      oauthCallbackRef.current = null;
      oauthCancelRef.current = null;
    },
    // Popup closed without completing → resolve the pending SDK requestCredential as null.
    onCancel: () => {
      oauthCancelRef.current?.();
      oauthCancelRef.current = null;
      oauthCallbackRef.current = null;
    },
  });
  const registerOAuthCallback = useCallback((cb: (credentialId: string, provider: string) => void) => {
    oauthCallbackRef.current = cb;
  }, []);
  const registerOAuthCancelled = useCallback((cb: () => void) => {
    oauthCancelRef.current = cb;
  }, []);

  const workflowId = useWorkflowId();
  useSDKBridge((effectiveReadOnly && !sdkBridge) ? null : {
    iframeRef,
    nodeId: id,
    workflowId,
    oauthConnect: effectiveReadOnly ? undefined : oauthConnect,
    onOAuthCreated: effectiveReadOnly ? undefined : registerOAuthCallback,
    onOAuthCancelled: effectiveReadOnly ? undefined : registerOAuthCancelled,
    getNodes: sdkBridge?.getNodes,
    updateNodeData: sdkBridge?.updateNodeData,
    readOnly: effectiveReadOnly,
  });

  return renderHtmlReactIframe({
    isJsx,
    htmlContent,
    jsxSource,
    clientSrcdoc,
    clientError,
    backendError,
    backendSrcdoc: (nodeOutput?.srcdoc as string) || '',
    transpiling,
    iframeRef,
    readOnly: effectiveReadOnly,
  });
}

interface RenderArgs {
  isJsx: boolean;
  htmlContent: string;
  jsxSource: string;
  clientSrcdoc: string;
  clientError: string | null;
  backendError: string | undefined;
  backendSrcdoc: string;
  transpiling: boolean;
  iframeRef: RefObject<HTMLIFrameElement | null>;
  readOnly: boolean;
}

function renderHtmlReactIframe({
  isJsx,
  htmlContent,
  jsxSource,
  clientSrcdoc,
  clientError,
  backendError,
  backendSrcdoc,
  transpiling,
  iframeRef,
  readOnly,
}: RenderArgs) {
  // JSX: client transpilation (instant) > backend output (fallback)
  // HTML: backend output, but only if there's actual content
  const error = isJsx ? (clientError || backendError) : backendError;
  const srcdoc = isJsx
    ? (clientSrcdoc || backendSrcdoc)
    : (htmlContent ? backendSrcdoc : '');

  if (error && !srcdoc) {
    return (
      <div className="w-full h-full flex items-center justify-center bg-red-950/30 border border-dashed border-red-800 rounded-md p-4">
        <div className="flex flex-col items-center gap-2 text-red-600 dark:text-red-400 max-w-full">
          <Code2 className="w-8 h-8 shrink-0" />
          <span className="text-xs text-center break-all">{error}</span>
        </div>
      </div>
    );
  }

  const hasContent = isJsx ? !!jsxSource : !!htmlContent;
  if (!hasContent && !srcdoc) {
    const Icon = isJsx ? Code2 : Globe;
    const label = isJsx
      ? (transpiling ? 'Transpiling...' : 'Write JSX to see preview')
      : 'No HTML content';
    return (
      <div className="w-full h-full flex items-center justify-center bg-muted/50 border border-dashed border-border dark:border-zinc-700 rounded-md">
        <div className="flex flex-col items-center gap-2 text-muted-foreground/70 dark:text-zinc-600">
          {transpiling ? <Loader2 className="w-8 h-8 animate-spin" /> : <Icon className="w-8 h-8" />}
          <span className="text-xs">{label}</span>
        </div>
      </div>
    );
  }

  const finalSrcdoc = srcdoc || (!isJsx && htmlContent
    ? `<!DOCTYPE html><html><head><style>body { margin: 0; padding: 8px; font-family: system-ui, sans-serif; background: transparent; color: #d4d4d8; font-size: 13px; }</style></head><body>${htmlContent}</body></html>`
    : '');

  if (!finalSrcdoc) return null;

  // Never grant author-controlled srcdoc the same-origin sandbox token. Without it the
  // document receives an opaque origin: scripts and the postMessage SDK still work, while
  // window.parent DOM/storage/session access is blocked by the browser. Public/read-only
  // surfaces also lose popup and top-navigation capabilities.
  return (
    <iframe
      ref={iframeRef}
      srcDoc={finalSrcdoc}
      sandbox={componentSandbox(readOnly)}
      className="w-full h-full border-0 bg-card"
      title={isJsx ? 'React component' : 'HTML content'}
    />
  );
}
