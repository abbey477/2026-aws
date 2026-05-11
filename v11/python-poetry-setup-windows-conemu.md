# Python + Poetry Setup on Windows (ConEmu Edition)

> **For a Java dev learning Python.**
> If you know Maven, you already know 80% of this — the names are just different.

---

## Java → Python Cheat Sheet

Before we start, here's the mental map:

| Java | Python |
|---|---|
| JDK | Python interpreter |
| Maven | Poetry |
| `pom.xml` | `pyproject.toml` |
| Maven Central | PyPI |
| `~/.m2/repository` | `.venv/` (per-project) |
| Classpath isolation | Virtual environment (`.venv`) |
| `mvn install` | `poetry install` |
| `mvn test` | `poetry run pytest` |

---

## What Each Tool Does (One Line Each)

- **Python** — the language and interpreter. Like the JDK.
- **pip** — installs Python libraries. Like a low-level Maven dependency fetcher. Ships with Python.
- **pipx** — installs Python *command-line tools* in isolation. Like having a separate clean install for each CLI.
- **Poetry** — your build tool. Manages dependencies, venvs, builds. Like Maven.
- **venv (`.venv`)** — an isolated Python install for one project. Like Maven's per-project classpath, but as a real folder.

---

## Step 1: Verify Python

Open ConEmu. Pick a shell (**Git Bash recommended** — Unix-style commands work as written).

```bash
python --version
```

You should see `Python 3.11.x` or `3.12.x`.

If "command not found," install Python from [python.org](https://www.python.org/downloads/). During install, **check the box "Add Python to PATH."**

---

## Step 2: Install pipx (Using pip)

```bash
python -m pip install --user pipx
```

The `--user` flag is critical. It keeps pipx out of system Python.

**What just happened:**
- pipx library installed at: `C:\Users\<you>\AppData\Roaming\Python\Python3xx\site-packages\pipx\`
- pipx command placed at: `C:\Users\<you>\.local\bin\pipx`

---

## Step 3: Add pipx to PATH

```bash
python -m pipx ensurepath
```

This edits your Windows PATH to include `~/.local/bin`.

> ⚠️ **Close ConEmu completely and reopen it.**
> Not just a new tab — the entire app. PATH changes only apply to newly-spawned processes.

Verify:

```bash
pipx --version
```

---

## Step 4: Install Poetry via pipx

```bash
pipx install poetry
```

**What just happened:**
- Poetry got its own isolated venv at: `C:\Users\<you>\pipx\venvs\poetry\`
- A `poetry` command shim was placed at: `C:\Users\<you>\.local\bin\poetry`

Verify:

```bash
poetry --version
```

---

## Step 5: Create Your Custom Venv Folder

Pick a path that fits your machine restrictions. Example: `C:/dev/venvs`

```bash
mkdir -p /c/dev/venvs
```

> 💡 In Git Bash, `C:\dev\venvs` is written as `/c/dev/venvs`.

---

## Step 6: Go to Your Project

Your scaffolded project has `pyproject.toml` inside `lambdas/sample-hello/`. Go there:

```bash
cd sample-lambda-hello-app/lambdas/sample-hello
```

Run **all Poetry commands from this folder**, not the repo root.

---

## Step 7: Check if Custom Path is Already Set

The scaffolder might already configure it:

```bash
cat poetry.toml
```

**If you see** `[virtualenvs]` with a `path` line → **skip Step 8**. The team already decided.

**If not, or no `poetry.toml` exists** → continue.

---

## Step 8: Configure Custom Venv Path (Project-Local)

```bash
poetry config virtualenvs.path C:/dev/venvs --local
```

The `--local` flag is the key part. It writes to `poetry.toml` **in this project only** — no global config touched.

Verify:

```bash
cat poetry.toml
```

You should see:

```toml
[virtualenvs]
path = "C:/dev/venvs"
```

**Keep this off the repo** so CI/CD is unaffected:

```bash
echo "poetry.toml" >> .gitignore
```

---

## Step 9: Install Dependencies

```bash
poetry install
```

Poetry reads `pyproject.toml`, resolves dependencies, creates the venv at your custom path, and installs everything.

**What just happened:**
A venv was created at `C:/dev/venvs/sample-hello-<hash>-py3.x/` containing:

- `bin/python` — project Python interpreter
- `bin/pip` — project pip
- `bin/pytest` — installed CLI tools
- `lib/python3.x/site-packages/` — all libraries (requests, pytest, etc.)

---

## Step 10: Verify Where the Venv Landed

```bash
poetry env info
```

The `Path:` line should point inside `C:/dev/venvs/`.

---

## Step 11: Run Your Code

```bash
poetry run pytest
poetry run python src/sample_hello/handler.py
```

No activation needed. `poetry run` finds the right Python automatically.

---

## TL;DR — All Commands

```bash
# One-time setup
python --version
python -m pip install --user pipx
python -m pipx ensurepath
# RESTART ConEmu entirely

pipx install poetry
poetry --version

mkdir -p /c/dev/venvs

# Per-project
cd sample-lambda-hello-app/lambdas/sample-hello
cat poetry.toml                                      # skip next line if path already set
poetry config virtualenvs.path C:/dev/venvs --local
echo "poetry.toml" >> .gitignore

poetry install
poetry env info
poetry run pytest
```

---

## Where Everything Lives

```
C:\Users\<you>\AppData\Local\Programs\Python\Python3xx\
    └── python.exe                                  ← system Python (the JDK)

C:\Users\<you>\.local\bin\
    ├── pipx                                        ← pipx command
    └── poetry                                      ← Poetry command (shim)

C:\Users\<you>\pipx\venvs\poetry\
    ├── bin\python                                  ← Poetry's own Python
    └── lib\...\poetry\                             ← Poetry's code + deps

C:\dev\venvs\sample-hello-<hash>-py3.x\             ← YOUR PROJECT'S VENV
    ├── bin\python                                  ← project Python
    ├── bin\pytest                                  ← installed CLI tools
    └── lib\...\site-packages\                      ← project libraries
```

**Three separate Python worlds.** None can break the others.

---

## Daily Workflow Cheat Sheet

| Task | Command |
|---|---|
| Add a runtime library | `poetry add requests` |
| Add a dev-only library | `poetry add --group dev pytest` |
| Remove a library | `poetry remove requests` |
| Install from `poetry.lock` (fresh clone) | `poetry install` |
| Run tests | `poetry run pytest` |
| Run a script | `poetry run python path/to/file.py` |
| See dependency tree | `poetry show --tree` |
| See venv info | `poetry env info` |
| Nuke and restart venv | `poetry env remove --all` then `poetry install` |

---

## Project Structure (Your Scaffold)

```
sample-lambda-hello-app/
├── lambdas/
│   └── sample-hello/                ← run Poetry commands here
│       ├── pyproject.toml           ← committed (deps + config)
│       ├── poetry.toml              ← gitignored (your venv path)
│       ├── poetry.lock              ← committed (exact versions)
│       ├── Makefile                 ← per-lambda shortcuts
│       ├── src/
│       │   └── sample_hello/
│       │       ├── __init__.py
│       │       └── handler.py       ← your Lambda code
│       └── test/
│           ├── __init__.py
│           └── test_handler.py      ← unit tests
│
├── .gitignore
├── Jenkinsfile                      ← CI/CD — don't touch
├── Makefile                         ← repo-wide shortcuts
└── README.md
```

---

## ConEmu Gotchas

1. **PATH changes need a full ConEmu restart.** Closing one tab isn't enough — close the whole app.
2. **Pick one shell and stick with it.** Mixing Git Bash and PowerShell across sessions causes weird PATH issues.
3. **Use forward slashes in Poetry paths** even on Windows: `C:/dev/venvs` not `C:\dev\venvs`. Saves headaches with escaping.

---

## Things to Forget About

These come up in old tutorials but **you don't need them with Poetry**:

- `requirements.txt` — replaced by `pyproject.toml`
- `setup.py` / `setup.cfg` — predecessors of `pyproject.toml`
- `pipenv` — competitor to Poetry, not used at your office
- Manually creating `.venv` with `python -m venv` — Poetry does it for you
- `source .venv/bin/activate` — use `poetry run` instead

---

## When Something Breaks

| Symptom | Fix |
|---|---|
| `poetry: command not found` | Restart ConEmu fully. Check `~/.local/bin` is in PATH. |
| Venv in wrong place | Check `poetry.toml`. Run `poetry env remove --all` then `poetry install`. |
| Wrong Python version | `poetry env use python3.12` then `poetry install` |
| Locked file conflicts after `git pull` | Take their `poetry.lock`, then run `poetry install`. Never hand-merge. |
| "Externally-managed-environment" error from pip | You forgot `--user`. Or you should be using `poetry add` instead. |

---

## Golden Rules

1. **Never `pip install` into system Python.** Always use `poetry add` inside a project, or `pipx install` for global tools.
2. **`poetry add` writes to `pyproject.toml`.** `pip install` does not. Always use Poetry.
3. **Commit `pyproject.toml` and `poetry.lock`.** Gitignore `poetry.toml` and the venv folder.
4. **One shell, one ConEmu lifecycle.** Restart after PATH changes.
