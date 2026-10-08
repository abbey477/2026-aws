# Writing a SKILL.md: Guide & Template

A **skill** is a folder of instructions, plus optional scripts and reference files, that an AI agent (e.g. Claude) loads when a task calls for it. The core of every skill is a `SKILL.md` file.

## How skills work

- **Frontmatter (`name`, `description`)** is always visible to the agent. The agent uses the `description` to decide *when* to load the skill.
- **Body** (everything below the frontmatter) loads only when the skill is triggered. This keeps the agent's context lean ("progressive disclosure").
- **Supporting files** (scripts, templates, references) are read or run only when the SKILL.md tells the agent to use them.

### Folder layout

```
my-skill-name/
├── SKILL.md          # required
├── scripts/          # optional: executable helpers (Python, Bash, etc.)
├── references/       # optional: docs the agent reads on demand
└── assets/           # optional: templates, images, fonts used in output
```

### Where skills live

| Tool | Location |
|---|---|
| Claude Code (personal) | `~/.claude/skills/<skill-name>/SKILL.md` |
| Claude Code (project) | `.claude/skills/<skill-name>/SKILL.md` |
| Claude.ai / Cowork | Upload or save via Settings → Skills |
| Claude API / Agent SDK | Uploaded via the Skills API or bundled with the agent |

---

## Sections at a glance

Only the frontmatter is required. The body is free-form Markdown, so use the sections that help and skip the rest.

| Section | Purpose | Needed? |
|---|---|---|
| Frontmatter | Name + when to trigger | **Required** |
| Overview | What the skill does, end result | Recommended |
| Inputs | What's needed before starting | Recommended |
| Steps | The workflow, in order | Recommended |
| Rules | Standing requirements | Recommended |
| Output format | Exact shape of the result | Recommended |
| Examples | Input → output pairs | Highly recommended |
| Edge cases | Off-path situations | Optional |
| Common mistakes | Known AI pitfalls | Optional |
| Resources | Pointers to supporting files | If files exist |
| Final checklist | Self-check before finishing | Optional |

---

## Annotated template

Copy this into `SKILL.md`, replace the content, and **delete the guidance comments** (`#` lines in the frontmatter, `<!-- -->` blocks in the body).

````markdown
---
name: my-skill-name
# Lowercase, hyphens, short. This is the skill's ID.

description: Does X for Y. Use when the user asks to ..., mentions ..., or uploads ...
# The MOST important line. The AI reads only this to decide whether to load the skill.
# Say WHAT it does + WHEN to use it, and list trigger words/phrases users actually say.
# Keep it to 1–2 sentences.
---

# Skill Name
<!-- 1–3 sentences: the goal and the end result.
     e.g. "Turns raw meeting notes into a one-page summary with decisions and action items." -->

## Inputs
<!-- What the agent needs before starting, and where it comes from.
     - Required vs optional inputs
     - What to do if something is missing (ask the user? use a default?)
     e.g. "Required: the meeting notes (pasted or uploaded). Optional: attendee list.
           If no date is given, ask for it." -->

## Steps
<!-- The workflow, in order. Number the steps.
     - One action per step; be concrete ("Group items by owner", not "Organize things")
     - Mention files/scripts at the step where they're used
     - Keep it to the essential path; put rare cases under Edge cases -->

## Rules
<!-- Standing requirements that apply throughout: tone, length, formatting, must-haves.
     - Explain WHY when it isn't obvious; the AI follows rules better when it knows the reason
       e.g. "Use first names only (the summary goes to an external client)."
     - Prefer positive phrasing ("Do X") over long lists of "Never..." -->

## Output format
<!-- Show exactly what the result should look like. A literal template works best:

     # Meeting Summary – {date}
     **Decisions:** ...
     **Action items:** | Owner | Task | Due |

     Also state the file type, length limits, or where it gets saved. -->

## Examples
<!-- 1–3 short input → output pairs. Usually the most effective section.
     - Show a typical case, plus one tricky case if you can
     - Use realistic examples; make them varied so the AI doesn't copy one too literally -->

## Edge cases
<!-- Situations that break the normal flow, and what to do about them.
     e.g. "If notes are in another language, summarize in English and note the source language."
     e.g. "If there are no action items, write 'None' instead of omitting the section." -->

## Common mistakes
<!-- Pitfalls you've actually seen the AI make. Add to this list over time as you test.
     e.g. "Don't invent due dates that aren't in the notes." -->

## Resources
<!-- Point to supporting files in the skill folder and say WHEN to use each one.
     The AI only opens them when told to, which keeps things efficient.
     e.g. "- `templates/summary.md`: base template, use for every summary
           - `references/glossary.md`: read if the notes contain unfamiliar acronyms
           - `scripts/extract.py`: run on .docx uploads to pull out the text" -->

## Final checklist
<!-- Quick self-check before the agent finishes. Keep it to 3–6 yes/no items.
     e.g. "- Every action item has an owner
           - Summary fits on one page
           - No placeholder text left" -->
````

---

## Filled-in example

```markdown
---
name: meeting-summary
description: Turns raw meeting notes or transcripts into a one-page summary with decisions and action items. Use when the user asks to summarize a meeting, recap a call, or extract action items from notes.
---

# Meeting Summary
Produces a concise, one-page summary of a meeting that can be sent to attendees.

## Inputs
- Required: meeting notes or transcript (pasted or uploaded).
- Optional: meeting date, attendee list. If the date is missing, ask for it.

## Steps
1. Read the full notes.
2. Identify decisions made (explicit agreements only).
3. Extract action items with owner and due date.
4. Write a 3–5 sentence overview of what was discussed.
5. Format using the template below.

## Rules
- Keep the summary under one page; it's read on phones.
- Use attendees' first names only.
- Quote decisions accurately; don't paraphrase numbers or dates.

## Output format
# Meeting Summary – {date}
**Overview:** 3–5 sentences
**Decisions:** bulleted list
**Action items:** table with Owner | Task | Due

## Edge cases
- No action items → write "None" rather than omitting the section.
- No owner stated → mark owner as "TBD".

## Common mistakes
- Don't invent due dates that aren't in the notes.

## Final checklist
- Every action item has an owner (or TBD)
- Fits on one page
- No placeholder text left
```

---

## Best practices

1. **Write the description carefully.** A vague one means the skill won't trigger when it should, or will trigger when it shouldn't.
2. **Be concrete.** Write instructions the way you'd brief a smart new colleague doing the task for the first time.
3. **Explain the "why" behind rules.** Models apply reasoning better than rote constraints.
4. **Keep SKILL.md lean.** Under ~500 lines is a good guideline; move bulky material into `references/`.
5. **Use scripts for deterministic work.** Parsing, validation and conversions are more reliable as code than prose.
6. **Test with real tasks and iterate.** Watch where the agent goes wrong, then update Rules, Edge cases or Common mistakes.
7. **Version control your skills.** Treat them like code: review changes and keep them in a repo.
