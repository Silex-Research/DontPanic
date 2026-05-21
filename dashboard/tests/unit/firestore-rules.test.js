// Plan 2026-05-09-004 F004 -- Firestore rules boundary.
//
// The realtime dashboard adapter allows authenticated browser reads of mirrored
// projection state, but all writes must flow through Admin SDK paths.

import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

const RULES = readFileSync(join(process.cwd(), '..', 'firestore.rules'), 'utf8');

describe('firestore.rules dashboard adapter boundary', () => {
  it('allows authenticated reads for dashboard clients', () => {
    expect(RULES).toContain('allow read: if request.auth != null;');
  });

  it('denies all client-side writes', () => {
    expect(RULES).toContain('allow write: if false;');
    expect(RULES).not.toContain('allow read, write: if false;');
  });

  it('documents the Admin SDK write path', () => {
    expect(RULES).toContain('All writes are server-side via Admin SDK');
    expect(RULES).toContain('client SDK writes are denied');
  });
});
