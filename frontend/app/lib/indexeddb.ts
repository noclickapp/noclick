// IndexedDB utility for persistent client-side storage across NoClick app
// Provides type-safe operations, connection pooling, and graceful fallbacks
// Used primarily for caching valtio state and other persistent data

interface StoredValue<T = any> {
  value: T;
  timestamp: number;
  version?: string;
}

interface IDBConfig {
  dbName: string;
  version: number;
  stores: Array<{
    name: string;
    keyPath?: string;
    autoIncrement?: boolean;
    indexes?: Array<{ name: string; keyPath: string; unique?: boolean }>;
  }>;
}

class IndexedDBManager {
  private dbPromise: Promise<IDBDatabase> | null = null;
  private config: IDBConfig;

  constructor(config: IDBConfig) {
    this.config = config;
  }

  private async getDB(): Promise<IDBDatabase> {
    if (!this.dbPromise) {
      this.dbPromise = new Promise((resolve, reject) => {
        if (!('indexedDB' in window)) {
          reject(new Error('IndexedDB not supported'));
          return;
        }

        const request = indexedDB.open(this.config.dbName, this.config.version);
        
        request.onerror = () => reject(request.error);
        request.onsuccess = () => resolve(request.result);
        
        request.onupgradeneeded = (event) => {
          const db = (event.target as IDBOpenDBRequest).result;
          
          this.config.stores.forEach(storeConfig => {
            if (!db.objectStoreNames.contains(storeConfig.name)) {
              const store = db.createObjectStore(storeConfig.name, {
                keyPath: storeConfig.keyPath,
                autoIncrement: storeConfig.autoIncrement
              });

              storeConfig.indexes?.forEach(index => {
                store.createIndex(index.name, index.keyPath, { unique: index.unique });
              });
            }
          });
        };
      });
    }
    
    return this.dbPromise;
  }

  async get<T>(storeName: string, key: string): Promise<T | null> {
    try {
      const db = await this.getDB();
      const tx = db.transaction(storeName, 'readonly');
      const store = tx.objectStore(storeName);
      
      return new Promise(resolve => {
        const request = store.get(key);
        request.onsuccess = () => {
          const result = request.result as StoredValue<T> | undefined;
          resolve(result?.value ?? null); // return .value, not everything
        };
        request.onerror = () => resolve(null);
      });
    } catch {
      return null;
    }
  }

  async getWithMetadata<T>(storeName: string, key: string): Promise<StoredValue<T> | null> {
    try {
      const db = await this.getDB();
      const tx = db.transaction(storeName, 'readonly');
      const store = tx.objectStore(storeName);

      return new Promise(resolve => {
        const request = store.get(key);
        request.onsuccess = () => {
          const result = request.result as StoredValue<T> | undefined;
          resolve(result ?? null);
        };
        request.onerror = () => resolve(null);
      });
    } catch {
      return null;
    }
  }

  async set<T>(storeName: string, key: string, value: T, metadata?: { version?: string }): Promise<boolean> {
    try {
      const db = await this.getDB();
      const tx = db.transaction(storeName, 'readwrite');
      const store = tx.objectStore(storeName);
      
      const storedValue: StoredValue<T> = {
        value,
        timestamp: Date.now(),
        ...metadata
      };
      
      return new Promise(resolve => {
        const request = store.put(storedValue, key);
        request.onsuccess = () => resolve(true);
        request.onerror = () => resolve(false);
      });
    } catch {
      return false;
    }
  }

  async delete(storeName: string, key: string): Promise<boolean> {
    try {
      const db = await this.getDB();
      const tx = db.transaction(storeName, 'readwrite');
      const store = tx.objectStore(storeName);
      
      return new Promise(resolve => {
        const request = store.delete(key);
        request.onsuccess = () => resolve(true);
        request.onerror = () => resolve(false);
      });
    } catch {
      return false;
    }
  }

  async has(storeName: string, key: string): Promise<boolean> {
    try {
      const db = await this.getDB();
      const tx = db.transaction(storeName, 'readonly');
      const store = tx.objectStore(storeName);
      
      return new Promise(resolve => {
        const request = store.getKey(key);
        request.onsuccess = () => resolve(request.result !== undefined);
        request.onerror = () => resolve(false);
      });
    } catch {
      return false;
    }
  }

  async clear(storeName: string): Promise<boolean> {
    try {
      const db = await this.getDB();
      const tx = db.transaction(storeName, 'readwrite');
      const store = tx.objectStore(storeName);
      
      return new Promise(resolve => {
        const request = store.clear();
        request.onsuccess = () => resolve(true);
        request.onerror = () => resolve(false);
      });
    } catch {
      return false;
    }
  }

  async getAllKeys(storeName: string): Promise<string[]> {
    try {
      const db = await this.getDB();
      const tx = db.transaction(storeName, 'readonly');
      const store = tx.objectStore(storeName);
      
      return new Promise(resolve => {
        const request = store.getAllKeys();
        request.onsuccess = () => resolve(request.result as string[]);
        request.onerror = () => resolve([]);
      });
    } catch {
      return [];
    }
  }

  async batchSet<T>(storeName: string, entries: Array<{ key: string; value: T }>): Promise<boolean> {
    try {
      const db = await this.getDB();
      const tx = db.transaction(storeName, 'readwrite');
      const store = tx.objectStore(storeName);
      
      const promises = entries.map(({ key, value }) => {
        const storedValue: StoredValue<T> = {
          value,
          timestamp: Date.now()
        };
        return store.put(storedValue, key);
      });
      
      return new Promise(resolve => {
        tx.oncomplete = () => resolve(true);
        tx.onerror = () => resolve(false);
      });
    } catch {
      return false;
    }
  }
}

// Default NoClick app configuration
const defaultConfig: IDBConfig = {
  dbName: 'noclick-app',
  version: 1,
  stores: [
    {
      name: 'valtio-cache',
      indexes: [
        { name: 'timestamp', keyPath: 'timestamp' }
      ]
    },
    {
      name: 'user-preferences'
    },
    {
      name: 'component-cache'
    }
  ]
};

// Singleton instance for the app
export const idb = new IndexedDBManager(defaultConfig);

// Convenient wrapper functions for the most common store
export const valtioCache = {
  get: <T>(key: string) => idb.get<T>('valtio-cache', key),
  getWithMetadata: <T>(key: string) => idb.getWithMetadata<T>('valtio-cache', key),
  set: <T>(key: string, value: T) => idb.set('valtio-cache', key, value),
  delete: (key: string) => idb.delete('valtio-cache', key),
  has: (key: string) => idb.has('valtio-cache', key),
  clear: () => idb.clear('valtio-cache')
};

export const userPreferences = {
  get: <T>(key: string) => idb.get<T>('user-preferences', key),
  set: <T>(key: string, value: T) => idb.set('user-preferences', key, value),
  delete: (key: string) => idb.delete('user-preferences', key),
  clear: () => idb.clear('user-preferences')
};

// Export the manager class for advanced usage
export { IndexedDBManager };
export type { IDBConfig, StoredValue };