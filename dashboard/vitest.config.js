import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    environment: 'jsdom',
    environmentOptions: {
      // F003 selector tests rely on URLSearchParams + history.replaceState
      // for ?project= persistence. jsdom blocks replaceState() from the
      // default about:blank origin, so pin the test URL to a real one.
      jsdom: { url: 'http://localhost/' },
    },
    globals: true,
    include: ['tests/**/*.test.js', 'functions/tests/**/*.test.js'],
    coverage: {
      include: ['lib/**/*.js'],
      reporter: ['text', 'lcov'],
    },
  },
});
