## Problem Summary
### Overview

The Topcoder Community App is the main application used to display challenges, handle registration, and accept submissions on the Topcoder platform.

You can find the source code here:

https://github.com/topcoder-platform/community-app

### Local deployment

Instructions for deploying and building the community app locally can be found here:

https://platform-ui.topcoder.com/dev-cen
## Step-by-step Plan
- Update affected service layer
- Add regression tests covering reproduction steps
## Test Plan
- pytest tests/unit
- npm run lint
## Risks
- Hidden call-sites may still use deprecated fields
- Rollback plan required for config changes
## Validation
- Unit tests for bug reproduction
- Smoke tests for impacted endpoints