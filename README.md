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
