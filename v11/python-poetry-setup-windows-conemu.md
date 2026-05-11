# Python + Poetry Setup on Windows (ConEmu Edition)

> **For a Java dev learning Python.**
> If you know Maven, you already know 80% of this — the names are just different.

---

## ⚠️ Read This First — Validate Before You Install

Corporate machines often come with Python, pip, and Poetry **pre-installed**.
Installing again can:

- Trigger group policy blocks
- Create conflicting versions
- Break the team's expected setup

**Always check if a tool exists before installing it.** Every section below starts with a `--version` check. If it works → skip the install.

---

## Java → Python Cheat Sheet

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
- **pip** — installs Python libraries. Ships with Python.
- **Poetry** — your build tool. Manages dependencies, venvs, builds. Like Maven.
- **venv (`.venv`)** — an isolated Python install for one project. Like Maven's per-project classpath, but as a real folder.
- **pipx** — installs Python CLI tools in isolation. Only needed if Poetry isn't already on the machine.

---

## Step 1: Validate Python

```bash
python --version
where python              # see where it's installed
```

### ✅ If you see `Python 3.11.x` or higher → done. Skip to Step 2.

**Typical install locations on Windows:**

| Where Python was installed from | Typical path |
|---|---|
| python.org installer (user) | `C:\Users\<you>\AppData\Local\Programs\Python\Python3xx\python.exe` |
| python.org installer (all users) | `C:\Program Files\Python3xx\python.exe` |
| Microsoft Store | `C:\Users\<you>\AppData\Local\Microsoft\WindowsApps\python.exe` |
| Corporate / pre-installed | Varies — `where python` will tell you |

### ❌ If "command not found":

Try alternatives first:

```bash
python3 --version
py --version
```

If any work → use that command name everywhere below (replace `python` with `python3` or `py`).

If none work → **install Python**:

1. Download from [python.org/downloads](https://www.python.org/downloads/)
2. During install, check **"Add Python to PATH"**
3. Restart ConEmu completely (close the app, reopen)
4. Re-run `python --version`

After install, the path will be `C:\Users\<you>\AppData\Local\Programs\Python\Python3xx\`.

---

## Step 2: Validate pip

```bash
python -m pip --version
```

This shows pip's version **and** its install path. Output looks like:

```
pip 23.x.x from C:\Users\<you>\AppData\Local\Programs\Python\Python3xx\Lib\site-packages\pip (python 3.x)
```

**Where pip lives:**

| Item | Path |
|---|---|
| pip library | `<python-install>\Lib\site-packages\pip\` |
| pip command | `<python-install>\Scripts\pip.exe` |
| Packages installed with `pip install` | `<python-install>\Lib\site-packages\` (avoid!) |
| Packages installed with `pip install --user` | `C:\Users\<you>\AppData\Roaming\Python\Python3xx\site-packages\` |

### ✅ If you see `pip 23.x` or similar → done. Skip to Step 3.

### ❌ If pip is missing (rare — usually ships with Python):

```bash
python -m ensurepip --upgrade
```

Or reinstall Python from python.org with "pip" checked during install.

---

## Step 3: Validate Poetry

```bash
poetry --version
where poetry              # see where it's installed
poetry about              # shows install path explicitly
```

### ✅ If you see `Poetry (version 1.8.x)` or `2.x.x` → done. Skip to Step 7.

This is the most likely case on a corporate machine.

**Where Poetry typically lives** (depends on install method):

| Install method | Command path | Poetry's own venv |
|---|---|---|
| curl installer | `C:\Users\<you>\AppData\Roaming\Python\Scripts\poetry.exe` | `C:\Users\<you>\AppData\Roaming\pypoetry\venv\` |
| pipx | `C:\Users\<you>\.local\bin\poetry.exe` | `C:\Users\<you>\pipx\venvs\poetry\` |
| Corporate-managed | Varies — `where poetry` tells you | Varies |

**Poetry's config and cache locations** (good to know for troubleshooting):

| Item | Path |
|---|---|
| Global config | `C:\Users\<you>\AppData\Roaming\pypoetry\config.toml` |
| Default venv cache | `C:\Users\<you>\AppData\Local\pypoetry\Cache\virtualenvs\` |
| Package cache | `C:\Users\<you>\AppData\Local\pypoetry\Cache\artifacts\` |

### ❌ If "command not found" — continue to Step 4.

---

## Step 4: Validate pipx (Only if Poetry Was Missing)

> Skip this section if Poetry is already installed.

```bash
pipx --version
where pipx
```

### ✅ If pipx works → skip to Step 6 (install Poetry via pipx).

**Where pipx lives** (after `pip install --user pipx`):

| Item | Path |
|---|---|
| pipx command | `C:\Users\<you>\.local\bin\pipx.exe` |
| pipx library | `C:\Users\<you>\AppData\Roaming\Python\Python3xx\site-packages\pipx\` |
| Tools installed by pipx | `C:\Users\<you>\pipx\venvs\<toolname>\` |
| Shims for those tools | `C:\Users\<you>\.local\bin\<toolname>.exe` |

### ⚠️ If you get "blocked by group policy":

Your machine restricts pipx. **Try Step 5 (curl install) instead.**

### ❌ If "command not found" — continue to Step 5.

---

## Step 5: Install Poetry via curl (Try First)

> Skip this if Poetry already works.

```bash
curl -sSL https://install.python-poetry.org | python -
```

Then **close ConEmu entirely** and reopen. Verify:

```bash
poetry --version
where poetry
```

**Where this installs Poetry:**

| Item | Path |
|---|---|
| Poetry command | `C:\Users\<you>\AppData\Roaming\Python\Scripts\poetry.exe` |
| Poetry's isolated venv | `C:\Users\<you>\AppData\Roaming\pypoetry\venv\` |
| Global config (created later) | `C:\Users\<you>\AppData\Roaming\pypoetry\config.toml` |

The installer prints the exact paths at the end — read its output.

### ✅ Works? → skip to Step 7.

### ❌ `curl: command not found` or blocked? → continue to Step 6.

---

## Step 6: Install Poetry via pipx (Fallback)

> Skip this if curl worked or Poetry already works.

Install pipx first:

```bash
python -m pip install --user pipx
python -m pipx ensurepath
```

**What just got installed:**

| Item | Path |
|---|---|
| pipx library | `C:\Users\<you>\AppData\Roaming\Python\Python3xx\site-packages\pipx\` |
| pipx command | `C:\Users\<you>\.local\bin\pipx.exe` |

**Close ConEmu entirely** and reopen. Then install Poetry:

```bash
pipx install poetry
poetry --version
```

**Where Poetry now lives:**

| Item | Path |
|---|---|
| Poetry command | `C:\Users\<you>\.local\bin\poetry.exe` |
| Poetry's isolated venv | `C:\Users\<you>\pipx\venvs\poetry\` |

### ❌ If "blocked by group policy":

Both install paths are blocked on your machine. **Contact IT or ask a teammate** — there's likely an approved internal install method.

---

## Step 7: Go to Your Project

Your `pyproject.toml` lives inside `lambdas/sample-hello/`. Run **all Poetry commands from this folder**.

```bash
cd sample-lambda-hello-app/lambdas/sample-hello
```

---

## Step 8: Validate the Scaffolded `poetry.toml`

The internal tool may have already created a `poetry.toml`. Check:

```bash
cat poetry.toml
```

### ✅ File exists with settings → **don't override it.** The team made these choices.

Common values you might see:

| Setting | What it means |
|---|---|
| `in-project = true` | Venv goes inside the project as `.venv/` |
| `path = "..."` | Venv goes in a specific folder |

### ❌ File doesn't exist → Poetry will use its default cache location. That's usually fine for a first run.

---

## Step 9: Install Dependencies

```bash
poetry install
```

Poetry reads `pyproject.toml`, resolves dependencies, creates the venv where `poetry.toml` says, and installs everything from `poetry.lock`.

---

## Step 10: Validate the Venv

```bash
poetry env info
```

The `Path:` line tells you exactly where the venv lives. Note it for future reference.

---

## Step 11: Run Your Code

```bash
poetry run pytest                              # run tests
poetry run python src/sample_hello/handler.py  # run code
```

No activation needed. `poetry run` finds the right Python automatically.

There's likely a `Makefile` in the project that wraps these commands. Try:

```bash
make help     # or: cat Makefile
make test
```

---

## TL;DR — Full Validation Flow

Copy/paste this whole block. Each line either passes (move on) or tells you what's missing:

```bash
# Validate
python --version                  # need 3.11+
python -m pip --version           # should work
poetry --version                  # most important — likely pre-installed

# Project setup
cd sample-lambda-hello-app/lambdas/sample-hello
cat poetry.toml                   # see team's venv choice (don't override)
poetry install                    # install deps
poetry env info                   # confirm venv location
poetry run pytest                 # run tests
```

If any validation fails, jump to the matching step above.

---

## Daily Workflow Cheat Sheet

| Task | Command |
|---|---|
| First setup after `git clone` | `poetry install` |
| Add a runtime library | `poetry add requests` |
| Add a dev-only library | `poetry add --group dev pytest` |
| Remove a library | `poetry remove requests` |
| Install after pulling new changes | `poetry install` |
| Run tests | `poetry run pytest` |
| Run a script | `poetry run python path/to/file.py` |
| See dependency tree | `poetry show --tree` |
| See venv info | `poetry env info` |
| Nuke and rebuild venv | `poetry env remove --all && poetry install` |

---

## Project Structure (Your Scaffold)

```
sample-lambda-hello-app/
├── lambdas/
│   └── sample-hello/                ← run Poetry commands here
│       ├── pyproject.toml           ← deps + config (committed)
│       ├── poetry.toml              ← Poetry config (committed by team)
│       ├── poetry.lock              ← exact versions (committed)
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

## What Lives Where — Full Map

The complete picture, by tool:

### Python (the JDK)

```
C:\Users\<you>\AppData\Local\Programs\Python\Python3xx\
├── python.exe                            ← the interpreter
├── Lib\site-packages\                    ← global libraries (don't pollute!)
│   └── pip\                              ← pip itself lives here
└── Scripts\
    └── pip.exe                           ← pip command
```

### User-level installs (pip install --user)

```
C:\Users\<you>\AppData\Roaming\Python\Python3xx\
└── site-packages\                        ← --user pip installs go here
    └── pipx\                             ← if you installed pipx
```

### pipx and its tools (if installed)

```
C:\Users\<you>\.local\bin\                ← added to PATH by `pipx ensurepath`
├── pipx.exe                              ← pipx command
└── poetry.exe                            ← Poetry shim (if installed via pipx)

C:\Users\<you>\pipx\venvs\
└── poetry\                               ← Poetry's isolated install (pipx method)
    ├── Scripts\python.exe
    └── Lib\...\poetry\
```

### Poetry (if installed via curl)

```
C:\Users\<you>\AppData\Roaming\Python\Scripts\
└── poetry.exe                            ← Poetry command (curl method)

C:\Users\<you>\AppData\Roaming\pypoetry\
├── venv\                                 ← Poetry's isolated install (curl method)
└── config.toml                           ← global Poetry config
```

### Poetry's cache (regardless of install method)

```
C:\Users\<you>\AppData\Local\pypoetry\Cache\
├── virtualenvs\                          ← default venv location (if no custom path)
└── artifacts\                            ← downloaded packages cache
```

### Your project's venv (the important one)

```
<wherever poetry.toml says>\
└── sample-hello-<hash>-py3.x\            ← YOUR PROJECT'S VENV
    ├── Scripts\python.exe                ← project Python
    ├── Scripts\pytest.exe                ← installed CLI tools
    └── Lib\site-packages\                ← project libraries
```

Each project gets its own venv. None can break the others.

**To find any of these on your machine, use `where <command>`:**

```bash
where python
where pip
where poetry
where pipx
```

---

## ConEmu Gotchas

1. **PATH changes need a full ConEmu restart.** Close the entire app, not just a tab.
2. **Stick with one shell** (Git Bash recommended). Mixing shells across sessions causes weird PATH issues.
3. **Use forward slashes in Poetry paths** even on Windows: `C:/dev/venvs` not `C:\dev\venvs`.

---

## Things to Forget About

These come up in old tutorials but **you don't need them with Poetry**:

- `requirements.txt` — replaced by `pyproject.toml`
- `setup.py` / `setup.cfg` — predecessors of `pyproject.toml`
- `pipenv` — competitor to Poetry, not used at your office
- `python -m venv .venv` — Poetry does this for you
- `source .venv/bin/activate` — use `poetry run` instead

---

## When Something Breaks

| Symptom | Fix |
|---|---|
| `python: command not found` | Try `python3` or `py`. Install from python.org if missing. |
| `poetry: command not found` | Restart ConEmu. If still broken, run validation flow Steps 4–6. |
| `pip: command not found` | Use `python -m pip ...` instead. |
| "blocked by group policy" | A tool is trying to run from a restricted folder. Try the other install method, or contact IT. |
| `poetry install` fails on a dependency | Check internal package registry access. Ask a teammate. |
| Venv in unexpected place | Check `poetry.toml`. Don't override it without asking the team. |
| Wrong Python version | `poetry env use python3.12` then `poetry install` |
| Conflicts in `poetry.lock` after `git pull` | Take their version, run `poetry install`. Never hand-merge. |
| Tests can't find modules | You're not using `poetry run`. Prefix with `poetry run pytest` instead of plain `pytest`. |

---

## Golden Rules

1. **Validate before installing.** Run `--version` first. Most corporate machines have tools pre-installed.
2. **Don't override `poetry.toml`** unless you've asked the team. They put it in the repo for a reason.
3. **Never `pip install` directly.** Always `poetry add` for project deps.
4. **Commit `pyproject.toml`, `poetry.lock`, `poetry.toml`.** Gitignore the venv folder.
5. **One shell, one ConEmu lifecycle.** Restart after any PATH change.
6. **Ask a teammate before contacting IT.** They've probably hit the same wall.

---

## Appendix: Install Method Comparison (Reference)

Two ways to install Poetry. Both produce an **isolated** install:

| | curl installer | pipx installer |
|---|---|---|
| Needs `curl`? | ✅ Yes | ❌ No |
| Needs pipx (and pip)? | ❌ No | ✅ Yes |
| Self-update? | `poetry self update` | `pipx upgrade poetry` |
| Install location | `%APPDATA%\pypoetry\` | `~\pipx\venvs\poetry\` |
| Blocked by group policy? | Sometimes | Often (as on this machine) |

### What NOT to do

❌ **`pip install poetry`** — puts Poetry in shared Python where its dependencies can clash with your projects. Always use curl or pipx.
