// SessionStorage utility for tab-specific client-side storage
// Provides the same API as valtioCache but uses sessionStorage for tab isolation
// Data persists across page refreshes but is cleared when the tab is closed

interface StoredValue<T = any> {
  value: T;
  timestamp: number;
  version?: string;
}

class SessionStorageManager {
  private prefix: string;

  constructor(prefix: string = 'noclick-session') {
    this.prefix = prefix;
  }

  private getStorageKey(key: string): string {
    return `${this.prefix}:${key}`;
  }

  async get<T>(key: string): Promise<T | null> {
    try {
      const storageKey = this.getStorageKey(key);
      const item = sessionStorage.getItem(storageKey);

      if (!item) return null;

      const parsed = JSON.parse(item) as StoredValue<T>;
      return parsed.value ?? null;
    } catch {
      return null;
    }
  }

  async getWithMetadata<T>(key: string): Promise<StoredValue<T> | null> {
    try {
      const storageKey = this.getStorageKey(key);
      const item = sessionStorage.getItem(storageKey);

      if (!item) return null;

      return JSON.parse(item) as StoredValue<T>;
    } catch {
      return null;
    }
  }

  async set<T>(key: string, value: T, metadata?: { version?: string }): Promise<boolean> {
    try {
      const storageKey = this.getStorageKey(key);
      const storedValue: StoredValue<T> = {
        value,
        timestamp: Date.now(),
        ...metadata
      };

      sessionStorage.setItem(storageKey, JSON.stringify(storedValue));
      return true;
    } catch {
      return false;
    }
  }

  async delete(key: string): Promise<boolean> {
    try {
      const storageKey = this.getStorageKey(key);
      sessionStorage.removeItem(storageKey);
      return true;
    } catch {
      return false;
    }
  }

  async has(key: string): Promise<boolean> {
    try {
      const storageKey = this.getStorageKey(key);
      return sessionStorage.getItem(storageKey) !== null;
    } catch {
      return false;
    }
  }

  async clear(): Promise<boolean> {
    try {
      // Only clear keys with our prefix
      const keysToRemove: string[] = [];
      for (let i = 0; i < sessionStorage.length; i++) {
        const key = sessionStorage.key(i);
        if (key?.startsWith(`${this.prefix}:`)) {
          keysToRemove.push(key);
        }
      }

      keysToRemove.forEach(key => sessionStorage.removeItem(key));
      return true;
    } catch {
      return false;
    }
  }
}

// Singleton instance for valtio session cache
const sessionManager = new SessionStorageManager('noclick-valtio');

export const valtioSessionCache = {
  get: <T>(key: string) => sessionManager.get<T>(key),
  getWithMetadata: <T>(key: string) => sessionManager.getWithMetadata<T>(key),
  set: <T>(key: string, value: T) => sessionManager.set(key, value),
  delete: (key: string) => sessionManager.delete(key),
  has: (key: string) => sessionManager.has(key),
  clear: () => sessionManager.clear()
};

export { SessionStorageManager };
export type { StoredValue };
