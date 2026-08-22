// XHR-based file upload with byte-level progress reporting. fetch() cannot
// observe request-body progress, so every surface that streams user files to
// R2 (presigned PUT) or a workspace volume (signed POST) routes its byte
// transfer through here to drive a progress bar.

export interface UploadHttpResponse {
    ok: boolean;
    status: number;
    statusText: string;
    /** Raw response body — callers parse JSON themselves when they need it. */
    text: string;
}

export function uploadWithProgress(
    url: string,
    body: Blob,
    opts?: {
        method?: 'PUT' | 'POST';
        headers?: Record<string, string>;
        /** Called with 0..1 as bytes leave the browser. */
        onProgress?: (fraction: number) => void;
    },
): Promise<UploadHttpResponse> {
    return new Promise((resolve, reject) => {
        const xhr = new XMLHttpRequest();
        xhr.open(opts?.method ?? 'POST', url);
        for (const [name, value] of Object.entries(opts?.headers ?? {})) {
            xhr.setRequestHeader(name, value);
        }
        const onProgress = opts?.onProgress;
        if (onProgress) {
            xhr.upload.onprogress = e => {
                if (e.lengthComputable && e.total > 0) onProgress(e.loaded / e.total);
            };
        }
        xhr.onload = () => {
            onProgress?.(1);
            resolve({
                ok: xhr.status >= 200 && xhr.status < 300,
                status: xhr.status,
                statusText: xhr.statusText,
                text: xhr.responseText,
            });
        };
        xhr.onerror = () => reject(new Error('Network error during upload'));
        xhr.onabort = () => reject(new Error('Upload aborted'));
        xhr.send(body);
    });
}
