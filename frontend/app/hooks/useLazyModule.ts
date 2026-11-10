import { useEffect, useState } from 'react';

const loaded = new Map<() => Promise<unknown>, unknown>();

/** A module loaded the first time a component draws with it (undefined until it arrives), then read at once by every
 *  component that asks with the same loader. For heavy drawings a page shows only sometimes: brand marks, flags. */
export function useLazyModule<T>(load: () => Promise<T>): T | undefined {
    const [module, setModule] = useState(() => loaded.get(load) as T | undefined);
    useEffect(() => {
        if (module) return;
        let live = true;
        load().then((value) => {
            loaded.set(load, value);
            if (live) setModule(() => value);
        });
        return () => {
            live = false;
        };
    }, [load, module]);
    return module;
}
