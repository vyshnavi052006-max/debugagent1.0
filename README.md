# DebugMate &mdash; Code Debugging Agent

**GENAI Internship &mdash; Milestone 2: Building Your First AI Agent**

## Overview

DebugMate is an autonomous code-debugging agent. Instead of just answering
questions about code, it **plans, acts, and remembers**: given an error
message or a broken snippet, it analyzes the problem, diagnoses the root
cause, generates a fix, **actually runs the fixed code in a live sandbox**,
and explains what happened &mdash; all in one autonomous pass. It stays
strictly inside its assigned domain and politely declines anything that
isn't about code/debugging.

- **Domain:** Code Debugging
- **Author:** V Vyshnavi

## Agent Capabilities

### 1. Multi-Step Task Planning & Execution
Every request runs through a fixed five-step plan, executed in order, with
progress tracked and shown to the user:
`Analyze -> Diagnose Root Cause -> Generate Fix -> Execute Fix -> Explain`.
If a step can't complete (e.g. no runnable language detected), the agent
reports that gracefully instead of crashing the whole task.

### 2. Tool/API Integration
DebugMate calls the free, public **Piston code execution API**
(`https://emkc.org/api/v2/piston`) to actually **run** the fixed code in
20+ languages and show real stdout/stderr &mdash; not a guess. No API key or
auth is required for Piston. If the sandbox is unreachable or the language
isn't supported, the agent **falls back gracefully** and still returns the
analysis and fix.

### 3. Context Memory & Decision Making
A lightweight JSON-backed memory store remembers, per session:
- the user's preferred/most-used programming language
- a rolling history of bug types it has fixed
- free-form constraints the user asks it to remember
The agent uses this memory to **personalize** its explanations (e.g. flagging
a recurring bug type it has already seen this session) and to fill in the
language when the user doesn't repeat it.

## How It Works

A FastAPI backend exposes `/api/chat`. On each message, the agent first runs
a fast domain guard (keyword heuristics, falling back to a one-word Groq
classification) to confirm the request is actually about code/debugging --
anything else gets a friendly refusal instead of an answer. For in-domain
requests, it chains several calls to the Groq LLM (`llama-3.1-8b-instant`,
free tier) to analyze, diagnose, and fix the bug, calls the Piston API to
execute the fix, and writes the result to its memory store before replying.
The frontend renders the agent's five steps as traceback-style "stack
frames" and animates an idle &rarr; planning &rarr; executing &rarr; done
status indicator.

## API Used

- **Groq API** (`https://console.groq.com`) &mdash; free LLM inference for
  analysis, diagnosis, fix generation, and explanation.
- **Piston API** (`https://emkc.org/api/v2/piston`) &mdash; free, no-auth
  code execution sandbox used as the agent's "Tool" capability.

## Setup Instructions (Local)

```bash
# 1. Clone and enter the project
git clone <your-repo-url>
cd debugmate

# 2. Create a virtual environment (optional but recommended)
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure your free Groq API key
cp .env.example .env
# then edit .env and paste your key from https://console.groq.com/keys

# 5. Run the server
uvicorn app:app --reload

# 6. Open the app
# http://127.0.0.1:8000
```

## Deployment

Any Python-friendly host works. Quickest options:

**Render** (recommended &mdash; `render.yaml` included):
1. Push this repo to GitHub.
2. On Render: New &rarr; Blueprint &rarr; select your repo.
3. Set the `GROQ_API_KEY` environment variable in the Render dashboard.
4. Deploy &mdash; Render reads `render.yaml` automatically.

**Railway / Heroku-style** (uses the included `Procfile`):
```bash
web: uvicorn app:app --host 0.0.0.0 --port $PORT
```
Set `GROQ_API_KEY` as an environment variable on the platform, never in code.

## Project Structure

```
debugmate/
├── app.py              # FastAPI routes, serves frontend + /api/chat
├── agent.py            # Planning, domain guard, orchestration
├── groq_client.py       # Groq LLM wrapper
├── piston_client.py     # Free code-execution tool integration
├── memory.py            # Persistent per-session memory store
├── static/
│   ├── index.html       # Frontend markup
│   ├── style.css         # Terminal/IDE themed styling
│   └── script.js         # Chat logic, status + memory UI
├── requirements.txt
├── .env.example
├── Procfile
├── render.yaml
└── README.md
```

## Live URL

`<https://debugagent1-0.onrender.com/>`

## Author

V Vyshnavi &mdash; Built for GENAI Internship &mdash; Milestone 2
