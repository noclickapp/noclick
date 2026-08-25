// Utility functions for handling paste operations in contenteditable elements
// Includes content serialization, element creation, and cursor management

import type { ContentItem } from '~/types/socket-schema.generated';

export interface PastedContent {
    id: string;
    type: 'image' | 'text' | 'drawing';
    preview?: string;
    lineCount?: number;
    content?: string;
    progress?: number;
    isLoading?: boolean;
    isUpdating?: boolean;
}

export interface ExtractedContent {
    text: string;
    attachments: Array<{
        id: string;
        type: 'image' | 'text' | 'drawing';
        data: string;
    }>;
    items: ContentItem[];
}

const DATA_URL_MIME_REGEX = /^data:([^;]+);base64,/i;

function inferMimeTypeFromDataUrl(value: string): string | undefined {
    const match = DATA_URL_MIME_REGEX.exec(value);
    return match?.[1];
}

// Default threshold for considering text as "large"
export const DEFAULT_LINE_THRESHOLD = 10;

/**
 * Creates an inline image element for insertion into contenteditable
 */
export function createInlineImageElement(
    id: string,
    preview: string
): HTMLElement {
    const span = document.createElement('span');
    span.contentEditable = 'false';
    span.className = 'inline-image-tag';
    span.dataset.pasteId = id;
    span.dataset.pasteType = 'image';
    span.dataset.pastePreview = preview;
    
    // Leave empty - React portal will render the actual component
    
    return span;
}

/**
 * Creates an inline text element for insertion into contenteditable
 */
export function createInlineTextElement(
    id: string,
    lineCount: number,
    content: string
): HTMLElement {
    const span = document.createElement('span');
    span.contentEditable = 'false';
    span.className = 'inline-text-tag';
    span.dataset.pasteId = id;
    span.dataset.pasteType = 'text';
    span.dataset.pasteContent = content;
    span.dataset.pasteLines = lineCount.toString();

    // Leave empty - React portal will render the actual component

    return span;
}

/**
 * Creates an inline drawing element for insertion into contenteditable
 */
export function createInlineDrawingElement(
    id: string,
    screenshot: string
): HTMLElement {
    const span = document.createElement('span');
    span.contentEditable = 'false';
    span.className = 'inline-drawing-tag';
    span.dataset.drawingId = id;
    span.dataset.drawingType = 'screenshot';
    span.dataset.drawingScreenshot = screenshot;

    // Leave empty - React portal will render the actual component

    return span;
}

/**
 * Creates an inline HTML element tag for insertion into contenteditable
 */
export function createInlineHtmlElement(
    id: string,
    tagName: string,
    noclickId: string,
    html?: string
): HTMLElement {
    const span = document.createElement('span');
    span.contentEditable = 'false';
    span.className = 'inline-html-tag';
    span.dataset.htmlElementId = id;
    span.dataset.htmlElementTagname = tagName;
    span.dataset.htmlElementNoclickid = noclickId;
    if (html) {
        span.dataset.htmlElementContent = html;
    }

    // Leave empty - React portal will render the actual component

    return span;
}

/**
 * Creates an inline context tag for insertion into contenteditable
 */
export function createInlineContextElement(
    id: string,
    value: string
): HTMLElement {
    const span = document.createElement('span');
    span.contentEditable = 'false';
    span.className = 'inline-context-tag';
    span.dataset.contextId = id;
    span.dataset.contextValue = value;

    // Leave empty - React portal will render the actual component

    return span;
}

/**
 * Inserts an element at the current cursor position in a contenteditable
 */
export function insertAtCursor(element: HTMLElement, editorEl: HTMLElement): void {
    const selection = window.getSelection();
    
    // If no selection, append to the end
    if (!selection || selection.rangeCount === 0) {
        editorEl.appendChild(element);
        const space = document.createTextNode('\u00A0');
        editorEl.appendChild(space);
        
        // Set cursor after the space
        const newRange = document.createRange();
        newRange.setStartAfter(space);
        newRange.collapse(true);
        selection?.removeAllRanges();
        selection?.addRange(newRange);
        return;
    }
    
    const range = selection.getRangeAt(0);
    
    // Make sure we're inserting within the editor
    if (!editorEl.contains(range.commonAncestorContainer)) {
        editorEl.appendChild(element);
        const space = document.createTextNode('\u00A0');
        editorEl.appendChild(space);
        
        // Set cursor after the space
        const newRange = document.createRange();
        newRange.setStartAfter(space);
        newRange.collapse(true);
        selection.removeAllRanges();
        selection.addRange(newRange);
        return;
    }
    
    // Delete any selected content
    range.deleteContents();
    
    // Create a document fragment to insert both element and space together
    const fragment = document.createDocumentFragment();
    fragment.appendChild(element);
    const space = document.createTextNode('\u00A0'); // Non-breaking space
    fragment.appendChild(space);
    
    // Insert the fragment
    range.insertNode(fragment);
    
    // Create new range positioned after the space
    const newRange = document.createRange();
    newRange.setStartAfter(space);
    newRange.setEndAfter(space);
    newRange.collapse(true);
    
    // Update selection
    selection.removeAllRanges();
    selection.addRange(newRange);
}

/**
 * Extracts text and attachments from contenteditable element
 */
export function extractContent(editorEl: HTMLElement, activePasteIds?: Set<string>): ExtractedContent {
    const attachments: ExtractedContent['attachments'] = [];

    type SequenceEntry =
        | { kind: 'text'; value: string }
        | { kind: 'image'; id: string; preview: string };

    const sequence: SequenceEntry[] = [];

    const addTextSequence = (value: string) => {
        if (!value) return;
        sequence.push({ kind: 'text', value });
    };

    const addBlockSeparator = () => {
        const last = sequence[sequence.length - 1];
        if (sequence.length === 0) return;
        if (last.kind === 'text' && last.value.endsWith('\n')) return;
        sequence.push({ kind: 'text', value: '\n' });
    };

    const processNode = (node: Node) => {
        if (node.nodeType === Node.TEXT_NODE) {
            addTextSequence(node.textContent || '');
            return;
        }

        if (node.nodeType !== Node.ELEMENT_NODE) {
            return;
        }

        const el = node as HTMLElement;

        if (el.nodeName === 'SCRIPT' || el.nodeName === 'STYLE') {
            return;
        }

        const pasteId = el.dataset?.pasteId;
        const pasteType = el.dataset?.pasteType;

        if (pasteType === 'image' && pasteId) {
            if (!activePasteIds || activePasteIds.has(pasteId)) {
                const preview = el.dataset?.pastePreview || '';
                sequence.push({ kind: 'image', id: pasteId, preview });
                attachments.push({
                    id: pasteId,
                    type: 'image',
                    data: preview
                });
            }
            return;
        }

        if (pasteType === 'text' && pasteId) {
            if (!activePasteIds || activePasteIds.has(pasteId)) {
                const content = el.dataset?.pasteContent || '';
                addTextSequence(content);
                attachments.push({
                    id: pasteId,
                    type: 'text',
                    data: content
                });
            }
            return;
        }

        // Check for drawing elements (inline-drawing-tag)
        const drawingId = el.dataset?.drawingId;
        const drawingType = el.dataset?.drawingType;
        const drawingScreenshot = el.dataset?.drawingScreenshot;

        if (drawingId && drawingType === 'screenshot' && drawingScreenshot) {
            // Add drawing as an image with special marker
            sequence.push({ kind: 'image', id: drawingId, preview: drawingScreenshot });
            attachments.push({
                id: drawingId,
                type: 'drawing', // Mark as drawing instead of regular image
                data: drawingScreenshot
            });
            return;
        }

        // Check for HTML element tags (inline-html-tag)
        const htmlElementId = el.dataset?.htmlElementId;
        const htmlElementTagname = el.dataset?.htmlElementTagname;
        const htmlElementNoclickid = el.dataset?.htmlElementNoclickid;
        const htmlElementContent = el.dataset?.htmlElementContent;

        if (htmlElementId && htmlElementTagname && htmlElementNoclickid) {
            // Add HTML element as a code block if content is available
            if (htmlElementContent) {
                // Format the HTML content nicely
                let formattedHtml = '';
                try {
                    // Try to parse and format the HTML
                    const tempDiv = document.createElement('div');
                    tempDiv.innerHTML = htmlElementContent;

                    // Clean up data-noclick attributes from the element and all descendants
                    const cleanElement = tempDiv.firstElementChild;
                    if (cleanElement) {
                        // Remove data-noclick attributes from the main element
                        const noclickAttrs = Array.from(cleanElement.attributes)
                            .filter(attr => attr.name.startsWith('data-noclick'));
                        noclickAttrs.forEach(attr => cleanElement.removeAttribute(attr.name));

                        // Remove data-noclick attributes from all descendants
                        const allElements = cleanElement.getElementsByTagName('*');
                        Array.from(allElements).forEach(el => {
                            const attrs = Array.from(el.attributes)
                                .filter(attr => attr.name.startsWith('data-noclick'));
                            attrs.forEach(attr => el.removeAttribute(attr.name));
                        });

                        formattedHtml = cleanElement.outerHTML;
                    } else {
                        formattedHtml = htmlElementContent;
                    }
                } catch {
                    formattedHtml = htmlElementContent;
                }
                // Add as a code block with triple backticks
                // Store the noclickId in a special marker that will be used for rendering only
                const codeBlock = `\`\`\`html[${htmlElementNoclickid}]\n${formattedHtml}\n\`\`\``;
                addTextSequence(codeBlock);
            } else {
                // Fallback to simple tag reference
                const elementText = `<${htmlElementTagname.toLowerCase()}>`;
                addTextSequence(elementText);
            }
            return;
        }

        // Check for context tags (inline-context-tag)
        const contextId = el.dataset?.contextId;
        const contextValue = el.dataset?.contextValue;

        if (contextId && contextValue) {
            // Add context as @mention-style text with brackets for unambiguous parsing
            addTextSequence(`@[${contextValue}]`);
            return;
        }

        if (el.nodeName === 'BR') {
            addTextSequence('\n');
            return;
        }

        if (el.nodeName === 'DIV' || el.nodeName === 'P') {
            addBlockSeparator();
        }

        let child = el.firstChild;
        while (child) {
            processNode(child);
            child = child.nextSibling;
        }
    };

    let child: ChildNode | null = editorEl.firstChild;
    while (child) {
        processNode(child);
        child = child.nextSibling;
    }

    const items: ContentItem[] = [];
    const textParts: string[] = [];

    const appendTextItem = (value: string) => {
        if (value.length === 0) {
            return;
        }
        const normalized = value.replace(/[\u00A0\u2000-\u200B\u2028\u2029]/g, ' ');
        if (items.length > 0 && items[items.length - 1].type === 'text') {
            const last = items[items.length - 1];
            last.text = `${last.text || ''}${normalized}`;
        } else {
            items.push({ type: 'text', text: normalized });
        }
        textParts.push(normalized);
    };

    sequence.forEach((entry) => {
        if (entry.kind === 'text') {
            appendTextItem(entry.value);
        } else {
            // Check if this is a drawing image by looking up the attachment
            const attachment = attachments.find(a => a.id === entry.id);
            const isDrawing = attachment?.type === 'drawing';

            if (isDrawing) {
                // For drawings, add a special prefix to mark it
                const imagePayload = {
                    url: `drawing:${entry.id}:${entry.preview}`
                    // No format property - drawing is identified by URL prefix only
                };
                items.push({ type: 'image_url', image_url: imagePayload });
            } else {
                // Regular image handling
                const format = inferMimeTypeFromDataUrl(entry.preview);
                const imagePayload = format
                    ? { url: entry.preview, format }
                    : { url: entry.preview };
                items.push({ type: 'image_url', image_url: imagePayload });
            }
        }
    });

    const cleanedText = textParts.join('')
        .replace(/\s+/g, ' ')
        .trim();

    return {
        text: cleanedText,
        attachments,
        items
    };
}

/**
 * Converts a File/Blob to base64 data URL
 */
export async function fileToDataURL(file: File | Blob): Promise<string> {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result as string);
        reader.onerror = reject;
        reader.readAsDataURL(file);
    });
}

/**
 * Resizes an image to a maximum dimension while maintaining aspect ratio
 */
export async function resizeImage(
    dataURL: string,
    maxWidth: number = 800,
    maxHeight: number = 600
): Promise<string> {
    return new Promise((resolve) => {
        const img = new Image();
        img.onload = () => {
            const canvas = document.createElement('canvas');
            const ctx = canvas.getContext('2d')!;
            
            let { width, height } = img;
            
            // Calculate new dimensions
            if (width > maxWidth || height > maxHeight) {
                const ratio = Math.min(maxWidth / width, maxHeight / height);
                width *= ratio;
                height *= ratio;
            }
            
            canvas.width = width;
            canvas.height = height;
            ctx.drawImage(img, 0, 0, width, height);
            
            resolve(canvas.toDataURL('image/jpeg', 0.8));
        };
        img.src = dataURL;
    });
}

/**
 * Generates a unique ID for pasted content
 */
export function generatePasteId(): string {
    const timestamp = Date.now().toString(36);
    const randomStr = Math.random().toString(36).substring(2, 9);
    return `paste-${timestamp}-${randomStr}`;
}

/**
 * Counts the number of lines in text
 */
export function countLines(text: string): number {
    return text.split('\n').length;
}

/**
 * Cleans up blob URLs to prevent memory leaks
 */
export function cleanupBlobUrl(url: string): void {
    if (url.startsWith('blob:')) {
        URL.revokeObjectURL(url);
    }
}
