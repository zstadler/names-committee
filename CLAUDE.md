# Instructions for AI agents

Start with [`PROJECT_NOTES.md`](PROJECT_NOTES.md) (Hebrew), the entry point to the project documentation.

## Spec-driven changes
- The spec (`PROJECT_NOTES.md` and `docs/`) is the primary source of truth. Every code change starts as a spec change: update or clarify the spec first, then change the code to match it.
- A requirement not yet implemented is marked "טרם מיושם" in the spec and phrased in future tense; once implemented and verified, it is marked "מיושם" and describes the current behaviour.

## GitHub
- GitHub is the project's progress record: push each commit as soon as it is made.
- Work on a temporary branch and merge through a PR with "squash and merge", then delete the branch, unless the user says to commit directly to `main`. Propose the PR title and description to the user for approval before creating the PR.
- Use `git` in a local clone and `gh` for API calls. In cloud sessions GraphQL is blocked, so use `gh api` REST calls (e.g. `gh api repos/zstadler/names-committee/pulls`).
- Commit author is the user: `git commit --author "zstadler <zeev.stadler@gmail.com>"`. Never override `user.name`/`user.email`, so the session's commit signature stays valid.
- Combine related changes across files into one commit, and keep the diff minimal.
- Each change and its reason go in the commit message; the docs describe only the current state.

## Commit messages, PRs and issues
- The title describes the improvement, not the problem.
- The body is a plain numbered list of concrete facts, each phrased with "now", e.g. "now ... instead of ...". A single-line description is a plain sentence.
- Put code-related terms in Markdown code quotes.
- Link issues with "Resolves #N", never "Fixes #N".
- End commit messages and PR descriptions with `Created with [Claude AI](https://claude.ai)` only: no `Co-Authored-By`, no session links, no other footers. Check a PR description's footer right after creating it and again before merging.

## Before and after pushing
- Take the list of pushed files from `git diff --name-only`, not from memory.
- After pushing, compare each file's remote blob SHA and mode with the local copy.
- Check each pushed commit via the API: the author login is `zstadler` and `.commit.verification.verified` is `true`.
