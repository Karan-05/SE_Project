# Test Plan

## Commands to Run
1. `git checkout feat/submissions-api`
2. `git merge develop`
3. `pnpm install`
4. `pnpm run lint`

## Expected Results
- The merge should complete without conflicts.
- `pnpm install` should not show any warnings.
- Linting should pass without errors.