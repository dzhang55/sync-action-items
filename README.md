# Arcade Takehome Agent

A barebones OpenAI Agents SDK loop wired to Arcade tools.

## Setup

1. Create an Arcade gateway/app with the tools you want this agent to use.
2. Make sure these Arcade tools are available to the Arcade account:
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

`agent.py` contains the allowed Arcade tool list, an `authorize_tool` helper, Arcade-to-OpenAI tool construction, and the interactive main loop.

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
