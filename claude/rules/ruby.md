---
globs: "*.rb,Gemfile,Rakefile,*.gemspec,Fastfile,Podfile,*.rake"
description: Ruby conventions for Fastlane, CocoaPods, Supabase tooling, Homebrew, build scripts
---

# Ruby Rules

## Naming
- Files: `snake_case.rb`
- Classes/Modules: `PascalCase`
- Methods/variables: `snake_case`
- Constants: `UPPER_SNAKE_CASE`
- Predicates: end with `?` (`valid?`, `empty?`)
- Mutators: end with `!` (`save!`, `normalize!`)
- No Hungarian notation

## Error Handling
- Define custom errors inheriting from `StandardError`, not `Exception`
- Rescue specific errors, never bare `rescue`
- Use `ensure` for cleanup (like `finally`)
- Raise with message: `raise ConfigError, "Missing API key for #{service}"`
- No `rescue => e; end` (swallowed errors)

## Style
- Prefer `do...end` for multi-line blocks, `{ }` for single-line
- Use `frozen_string_literal: true` pragma in all files
- Prefer `&:method_name` for simple blocks (`items.map(&:name)`)
- Use guard clauses over nested conditionals
- No `and`/`or` — use `&&`/`||`

## Fastlane Specific
- Lanes: `snake_case` (`lane :build_and_test`)
- Use `UI.message`, `UI.success`, `UI.error` — not `puts`
- Store signing/provisioning config in `Matchfile`, not inline
- Use `gym` for builds, `scan` for tests, `pilot` for TestFlight
- No hardcoded bundle IDs — use environment variables or `Appfile`

## CocoaPods/Podfile
- Pin major versions: `pod 'Alamofire', '~> 5.0'`
- No `pod install` in CI without `--repo-update` on first run
- Keep `Podfile.lock` in version control

## Testing
- Framework: RSpec (preferred) or Minitest
- Use `let` and `subject` for setup, `before` for actions
- `describe` for classes/methods, `context` for conditions, `it` for behavior
- No testing private methods directly — test through public interface

## Security
- No `system()` or backticks with user input — use `Open3.capture3`
- No `eval()` or `instance_eval` with untrusted strings
- No secrets in Gemfile or Fastfile — use `.env` + `dotenv` or CI secrets
- Validate external input before processing

## Patterns to Avoid
- Monkey-patching core classes in library code
- `method_missing` without `respond_to_missing?`
- Deep inheritance — prefer modules and composition
- `require` without checking existence first in optional dependencies
