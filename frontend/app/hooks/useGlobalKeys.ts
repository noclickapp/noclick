import { useEffect } from 'react';

export function useGlobalKeys(keyHandlers: {
    [key: string]: (event: KeyboardEvent) => void;
}) {
    useEffect(() => {
        const handleKeyDown = (event: KeyboardEvent) => {
            const handler = keyHandlers[event.key];
            if (handler) {
                handler(event);
            }
        };

        document.addEventListener('keydown', handleKeyDown);

        return () => {
            document.removeEventListener('keydown', handleKeyDown);
        };
    }, [keyHandlers]);
}
