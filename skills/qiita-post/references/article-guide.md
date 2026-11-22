# Writing the article

## Scope

- Cover the topic the user asked for. Without one, cover the main topic of the
  source that reached a conclusion. Ask only when the source has several
  unrelated topics and none stands out.
- Write the article in the language of the conversation (usually Japanese).

## Write the result, not the chat log

- Present the final, converged answer. When the conversation refined an answer
  step by step (e.g. a setting extended over several turns), the article shows
  only the integrated final version.
- Mention an earlier attempt only when its failure teaches something
  ("X alone does not cover case Y").
- Write as the author's own article. Do not refer to "the assistant", "this
  chat", or ChatGPT/Claude unless the user asks to.

## Fidelity

- Add no facts, numbers, versions, or links that are not in the source. Keep
  the source URLs the conversation cited, at the claim they support.
- Keep every caveat. Anything the conversation called unverified stays marked
  as unverified (e.g. in a `:::note warn` block). Never present an untested
  setting as tested.
- Drop chat-only links (`sandbox:/...`, attachment links, local file links).

## Privacy

Remove or generalize, and list what you changed in the report to the user:

- names, account or user names, email addresses, honorifics addressed to the user;
- absolute local paths that contain a user name (write `%USERPROFILE%\...`, `~/...`);
- private repository, organization, host, or project names;
- tokens, keys, internal URLs, and anything the user called private.

## Structure

1. Title: the problem and the fix, in words people search for.
2. Introduction: who hits this problem and what the article solves.
3. Conclusion first (TL;DR).
4. Environment, only with versions stated in the source.
5. Steps or explanation, with code blocks tagged by language.
6. Caveats and unverified points.
7. References: the cited URLs.

## Tags

1-5 tags, using existing Qiita tag names without spaces (e.g. `GitHubCopilot`,
`VSCode`, `Python`, `PowerShell`).
