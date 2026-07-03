# Sync Action Items

Agent for transforming Notion Action Items into Linear issues. Backed by OpenAI Agents SDK and Arcade.dev for tools.

## Setup

1. Create an Arcade account and an OpenAI account.
2. Make sure these Arcade tools are available to your Arcade account:
   - `NotionToolkit.GetPageContentById`
   - `NotionToolkit.GetPageContentByTitle`
   - `NotionToolkit.SearchByTitle`
   - `Linear.CreateIssue`
3. Copy `.env.example` to `.env` and fill in your Arcade and OpenAI values.
4. Install dependencies:

```bash
uv sync
```

## Usage

Start the interactive agent:

```bash
uv run python agent.py
```

Reset saved defaults and teammate aliases before starting:

```bash
uv run python agent.py --reset-config
```

## Evals

Run the live LLM evals:

```bash
uv run python -m evals.runner
```

The eval runner runs each case 3 times and runs 10 total evals at a time by default.
Override this when needed:

```bash
AGENT_EVAL_CONCURRENCY=4 uv run python -m evals.runner
AGENT_EVAL_RUNS_PER_CASE=1 uv run python -m evals.runner
```

## System Overview

`agent.py`: The main OpenAI Agents SDK agent with Arcade tools.

`config.py`: Tools to read/write config state, stored in json files. These tools write to 1) config.json for Linear/Notion default values and 2) linear_teammates.json for a mapping from nicknames to Linear usernames (Linear tool does not support listing teammates).

`evals/runner.py`: Evals runner with mock tools to score the agent.

`evals/cases.py`: The individual eval cases for the runner.

## Limitations

The Notion tool exports in markdown, which excludes rich text formatting like @mentions and checkboxes. For this reason, I scoped this agent down to explicitly search for bullet points within a Action Items section.

Neither Notion nor Linear support listing members. Combined with the @mention limitation above, we can't easily map identities across Notion users and Linear users. To get around this, the agent requires users to copy/paste their Linear members list, and then maintains its own state mapping Linear members to names/nicknames.


## Extensions

- Deterministic parsing of the Notion doc rather than relying on the LLM.
- Maintaining prior synced items, for example in SQLite.
- Integrate with Slack tool in order to send a summary of synced action items to the team.
