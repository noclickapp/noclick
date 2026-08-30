// crypto.randomUUID exists only in secure contexts (https, localhost). A
// self-hosted instance served over plain http on a LAN hostname is neither,
// and the dashboard died on its first request id (2026-08-31). getRandomValues
// has no such restriction, so fill the gap with RFC 4380 v4 built from it.
if (typeof crypto !== 'undefined' && !('randomUUID' in crypto)) {
    (crypto as Crypto & { randomUUID: () => string }).randomUUID = () => {
        const bytes = crypto.getRandomValues(new Uint8Array(16));
        bytes[6] = (bytes[6] & 0x0f) | 0x40;
        bytes[8] = (bytes[8] & 0x3f) | 0x80;
        const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
        return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
    };
}

export {};
