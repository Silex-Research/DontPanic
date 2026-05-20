// ── Operator-role auth gate for state-changing callables ──
// Plan 2026-05-09-004 F003. Maps Firebase Auth identity → DontPanic role
// (Operator | Observer) using the role allowlist documented in
// USE_CASES.md. Observer is read-only; only Operator can fire mutations
// from the dashboard surface (D003).
//
// Allowlist source of truth is a Firebase Functions environment config value
// (`dontpanic.operator_uids`, semicolon-separated). The list is read once
// per process — operators wanting to update it redeploy. For local emulator
// runs the loader also reads `DONTPANIC_OPERATOR_UIDS` from process.env.

export const ROLE_OPERATOR = 'operator';
export const ROLE_OBSERVER = 'observer';

export class AuthError extends Error {
  constructor(code, message) {
    super(message);
    this.name = 'AuthError';
    this.code = code;
  }
}

export function parseOperatorAllowlist(raw) {
  if (!raw) return new Set();
  return new Set(
    String(raw)
      .split(/[;,\s]+/)
      .map((s) => s.trim())
      .filter((s) => s.length > 0),
  );
}

export function resolveRole({ authContext, operatorUids }) {
  if (!authContext || !authContext.uid) {
    throw new AuthError('unauthenticated', 'sign-in required');
  }
  if (operatorUids && operatorUids.has(authContext.uid)) return ROLE_OPERATOR;
  if (authContext.token && authContext.token.dontpanic_role === ROLE_OPERATOR) {
    return ROLE_OPERATOR;
  }
  return ROLE_OBSERVER;
}

export function requireOperator(context, operatorUids) {
  const role = resolveRole({
    authContext: context && context.auth,
    operatorUids,
  });
  if (role !== ROLE_OPERATOR) {
    throw new AuthError(
      'permission-denied',
      'Operator role required for state-changing actions',
    );
  }
  return role;
}
