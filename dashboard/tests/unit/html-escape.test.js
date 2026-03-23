import { describe, it, expect } from 'vitest';
import { esc } from '../../lib/html-escape.js';

describe('esc', () => {
  it('returns empty string for null', () => {
    expect(esc(null)).toBe('');
  });

  it('returns empty string for undefined', () => {
    expect(esc(undefined)).toBe('');
  });

  it('escapes ampersands', () => {
    expect(esc('a & b')).toBe('a &amp; b');
  });

  it('escapes less-than and greater-than angle brackets', () => {
    expect(esc('<script>')).toBe('&lt;script&gt;');
  });

  it('escapes double quotes', () => {
    expect(esc('"quoted"')).toBe('&quot;quoted&quot;');
  });

  it('escapes mixed dangerous HTML content', () => {
    expect(esc('<img src="x" onerror="alert(1 & 2)">')).toBe(
      '&lt;img src=&quot;x&quot; onerror=&quot;alert(1 &amp; 2)&quot;&gt;'
    );
  });

  it('passes through safe strings unchanged', () => {
    expect(esc('Hello, world!')).toBe('Hello, world!');
  });

  it('coerces non-string values to string before escaping', () => {
    expect(esc(42)).toBe('42');
  });
});
