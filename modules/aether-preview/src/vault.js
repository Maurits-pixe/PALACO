const DATABASE_NAME = 'palaco-aether-vault';
const STORE_NAME = 'encrypted-files';
const DATABASE_VERSION = 1;

function openVault() {
  return new Promise((resolve, reject) => {
    if (!globalThis.indexedDB) {
      reject(new Error('Lokale browseropslag is niet beschikbaar.'));
      return;
    }
    const request = indexedDB.open(DATABASE_NAME, DATABASE_VERSION);
    request.onupgradeneeded = () => {
      if (!request.result.objectStoreNames.contains(STORE_NAME)) {
        request.result.createObjectStore(STORE_NAME, { keyPath: 'id' });
      }
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(new Error('De lokale kluis kon niet worden geopend.'));
  });
}

async function requestInVault(mode, action) {
  const database = await openVault();
  try {
    return await new Promise((resolve, reject) => {
      const transaction = database.transaction(STORE_NAME, mode);
      let result;
      const request = action(transaction.objectStore(STORE_NAME));
      request.onsuccess = () => { result = request.result; };
      request.onerror = () => reject(new Error('De lokale kluisbewerking is mislukt.'));
      transaction.oncomplete = () => resolve(result);
      transaction.onerror = () => reject(new Error('De lokale kluisbewerking is mislukt.'));
      transaction.onabort = () => reject(new Error('De lokale kluisbewerking is afgebroken.'));
    });
  } finally {
    database.close();
  }
}

export function listVaultItems() {
  return requestInVault('readonly', store => store.getAll());
}

export function saveVaultItem(item) {
  return requestInVault('readwrite', store => store.put(item));
}

export function removeVaultItem(id) {
  return requestInVault('readwrite', store => store.delete(id));
}
