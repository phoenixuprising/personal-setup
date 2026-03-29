---
name: check-github-before-debugging
enabled: true
event: prompt
conditions:
  - field: user_prompt
    operator: regex_match
    pattern: (?i)(error|bug|fix|broken|not\s+working|diagnos|debug|crash|fail|issue|problem|troubleshoot)
---

**Before investigating the codebase, check GitHub first:**

1. Search open issues: `mcp__plugin_github_github__search_issues` or `gh issue list`
2. Search open PRs: `mcp__plugin_github_github__list_pull_requests` or `gh pr list`
3. Check closed issues/PRs too — the fix may already exist or be in progress

Only proceed to reading code after confirming there's no existing issue or PR addressing this.
