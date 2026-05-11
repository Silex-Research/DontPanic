// Stub Firestore client for the Firebase realtime adapter tests.
// Mirrors the minimal `{ collection(path) → { onSnapshot } }` shape that
// dashboard/config-firebase.js expects from defaultSdkLoader. The stub fires
// onNext synchronously with the fixture data so tests don't need real timers.

export function createFirestoreStub(fixture) {
  const listeners = new Map(); // path -> { onNext, onErr }
  const stub = {
    collection(path) {
      return {
        onSnapshot(onNext, onErr) {
          listeners.set(path, { onNext, onErr });
          const docs = readDocsForPath(fixture, path);
          if (docs !== undefined) {
            onNext(makeSnapshot(docs));
          }
          return function unsubscribe() {
            listeners.delete(path);
          };
        },
      };
    },
    // Test-only hooks
    _emit(path, docs) {
      const entry = listeners.get(path);
      if (entry) entry.onNext(makeSnapshot(docs));
    },
    _emitError(path, err) {
      const entry = listeners.get(path);
      if (entry && entry.onErr) entry.onErr(err);
    },
    _listenerCount() {
      return listeners.size;
    },
    _hasPath(path) {
      return listeners.has(path);
    },
  };
  return stub;
}

function readDocsForPath(fixture, path) {
  // Path shape: `projects/{project_id}/{stream}`
  const parts = path.split('/');
  if (parts.length !== 3 || parts[0] !== 'projects') return undefined;
  const stream = parts[2];
  return Array.isArray(fixture[stream]) ? fixture[stream] : [];
}

function makeSnapshot(docs) {
  return {
    size: docs.length,
    forEach(cb) {
      for (const d of docs) {
        cb({ data: () => d });
      }
    },
  };
}
