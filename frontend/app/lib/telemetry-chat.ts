export function installChatTelemetry(): void {}

export function trackChatSendStarted(_args: {
    requestId: string;
    model: string | null;
    contentLength: number;
    imageCount: number;
    hasWorkflowContext: boolean;
    conversationId: string | null;
}): void {}
