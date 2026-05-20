// Plan 2026-05-09-004 F003 — auth gate unit tests.
//
// USE_CASES.md role matrix: only Operator can fire mutations from the
// dashboard surface. Observer is read-only. Unauthenticated calls are
// refused at the function boundary regardless of role.

import { describe, it, expect } from 'vitest';
import {
  parseOperatorAllowlist,
  resolveRole,
  requireOperator,
  ROLE_OPERATOR,
  ROLE_OBSERVER,
  AuthError,
} from '../lib/auth.js';

describe('parseOperatorAllowlist', () => {
  it('returns empty set for empty / null input', () => {
    expect(parseOperatorAllowlist('').size).toBe(0);
    expect(parseOperatorAllowlist(null).size).toBe(0);
    expect(parseOperatorAllowlist(undefined).size).toBe(0);
  });

  it('splits on semicolons, commas, and whitespace', () => {
    const s = parseOperatorAllowlist('uid-a;uid-b, uid-c\nuid-d');
    expect(s.has('uid-a')).toBe(true);
    expect(s.has('uid-b')).toBe(true);
    expect(s.has('uid-c')).toBe(true);
    expect(s.has('uid-d')).toBe(true);
    expect(s.size).toBe(4);
  });

  it('trims whitespace', () => {
    const s = parseOperatorAllowlist('  uid-a  ;  uid-b  ');
    expect(s.has('uid-a')).toBe(true);
    expect(s.has('uid-b')).toBe(true);
  });
});

describe('resolveRole', () => {
  it('refuses to resolve a role when there is no authContext.uid', () => {
    expect(() =>
      resolveRole({ authContext: null, operatorUids: new Set(['x']) }),
    ).toThrowError(AuthError);
    expect(() =>
      resolveRole({ authContext: {}, operatorUids: new Set(['x']) }),
    ).toThrowError(AuthError);
  });

  it('maps allowlisted UID → operator', () => {
    expect(
      resolveRole({
        authContext: { uid: 'uid-a' },
        operatorUids: new Set(['uid-a']),
      }),
    ).toBe(ROLE_OPERATOR);
  });

  it('maps custom claim dontpanic_role=operator → operator', () => {
    expect(
      resolveRole({
        authContext: { uid: 'uid-x', token: { dontpanic_role: 'operator' } },
        operatorUids: new Set(),
      }),
    ).toBe(ROLE_OPERATOR);
  });

  it('falls back to observer for authed but unprivileged users', () => {
    expect(
      resolveRole({
        authContext: { uid: 'uid-x' },
        operatorUids: new Set(['uid-a']),
      }),
    ).toBe(ROLE_OBSERVER);
  });
});

describe('requireOperator', () => {
  it('throws unauthenticated when there is no auth at all', () => {
    expect(() => requireOperator({}, new Set(['uid-a']))).toThrowError(
      /sign-in required/,
    );
  });

  it('throws permission-denied for observer role', () => {
    expect(() =>
      requireOperator({ auth: { uid: 'uid-other' } }, new Set(['uid-a'])),
    ).toThrowError(/Operator role required/);
  });

  it('returns operator for an allowlisted UID', () => {
    expect(
      requireOperator({ auth: { uid: 'uid-a' } }, new Set(['uid-a'])),
    ).toBe(ROLE_OPERATOR);
  });
});
