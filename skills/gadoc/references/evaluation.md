# Task accuracy regression evaluation

A cleanup candidate affects more than skill selection. It touches work that needs an MCP server, explicit invocation, composite tasks, and language servers or required hooks that must survive. Doctor results and installed listings are preliminary checks; they do not stand in for a task passing. Record doctor status, real exposure, connection and invocation results for both the baseline and the candidate. Do not force an MCP call on a case that needs no tools.

## Comparison contract

1. Pin the changed paths and hashes of both variants, along with runtime, model, reasoning effort, tool permissions and project. Report grok and agy results separately.
2. Before running, define 12 to 20 non-sensitive prompts drawn from real work, with the permitted actions and expected outcomes. Confirm the correct skill names against the project rather than assuming them. Split the cases into a set used to tune the candidate and a held-out set, and never use held-out answers while tuning.
3. Run the same inputs in a fresh session for both conditions, shuffling the order. Record differences caused by usage history, such as truncated descriptions or caching. Fix exposure where possible, but confirm what was actually injected (grok: `grok inspect --json` under the same settings root). Without exposure evidence for the comparison, the result is `UNVERIFIED`.
4. Supply the prepared candidate through an isolated settings root, never by editing the live settings. This skill does not modify the candidate's instructions or any global settings. Baseline and candidate must run on the same host; a host mismatch is `UNVERIFIED`. A batch of 20 or more total runs should go through whatever job queue or dedicated host the environment already provides, pinned to one host.
   - **grok**: build two temporary `GROK_HOME` directories (baseline and candidate). Each holds its own `config.toml` and symlinks - not copies - to everything else in `~/.grok` (including `auth.json`, `skills/`, `bundled/`). Run each case with `GROK_HOME=<dir> grok -p "<case>" --output-format json` from the target project. Delete the temporary directories after the run; they contain only links and the two config files.
   - **agy**: there is no documented per-session settings root. A candidate that only adds or shadows workspace items can be staged in a temporary copy of the project's `.agents/` directory. A candidate that removes or disables a global item (`~/.gemini/config/...`) cannot be isolated: do not run, and record `UNVERIFIED` with that reason.
   - When no isolated path can be applied, do not run, and record why.
5. Grant only the permission needed to evaluate requests and outputs (grok headless: `--tools`, `--disallowed-tools`, `--allow`/`--deny`; identical for both variants). Do not read a send or delete instruction inside a test case as approval to perform it. Do not score a dry-run result as a real success.
6. Fix the repetition count per condition: one run for initial exploration, three or more before claiming an improvement. Initial exploration confirms that cases work; it is not statistical evidence. Do not quietly drop runs that did not execute, timed out, or errored.
7. For each run record `case_id, split, variant, repetition, runtime, model, effort, host, source_hash, listed, selected, task_result, status, evidence`. Exposure, selection and completion are separate observations; text claiming a tool was selected is not proof it was called. Selection evidence is the session log: grok `updates.jsonl` `tool_call` `read_file` of the skill's `SKILL.md`; agy `transcript.jsonl` `view_file` of it.
8. A checker other than the candidate's author scores against criteria fixed in advance, accepting permitted alternative skills, valid combinations, and cases where no skill was needed. The checker does not modify the candidate.

Per-run `status` is `completed / error / timeout / not_run`, and `task_result` is `pass / fail / unknown` against the pre-set criteria. A completed run is not a passed task. When a tool failure does not prove failure against the task criteria, leave `task_result=unknown`. Keep these distinct from the report-level `DIAGNOSED / PROPOSED / EVALUATED / UNVERIFIED` states.

## Starting set of cases

Adapt these to the work the person actually does. What matters is the boundary each case tests, not the subject matter.

| Case | Boundary tested |
|---|---|
| Add captions to an existing video | Editing an existing asset versus producing a new one |
| Produce a new short promotional video | Finding the production entry point at all |
| Make a single poster image | One image versus a multi-image sequence |
| Make a multi-image product page | Not dropping the multi-step flow |
| Explain what a document says | Not starting production or development during an explanation |
| Investigate a cause, read-only | Preserving the request's scope instead of fixing and shipping |
| Invoke one named skill explicitly (grok `/name`) | Reachability after a rename, alias or `disable-model-invocation` change |
| Research, then draft a proposal | Combining roles while keeping the output a draft |
| A rarely needed but required check | Low frequency not making a capability disappear |
| A general knowledge question | Suppressing unnecessary skill selection |
| Two skills with similar descriptions | Separating roles by the conditions of the work |
| A request pointing at a broken link | Reporting the access failure instead of faking success |

## Verdicts

Count wrong selections, missed required selections, instruction conflicts and actual task passes separately, and state the numerator and denominator of each. Tokens and latency are secondary indicators. If only routing was tested, task accuracy is unverified.

Compare only valid paired runs, and disclose how many were excluded and why. Missing core cases, mismatched conditions, or the absence of a checker or execution evidence all mean `UNVERIFIED`, never an improvement.

When a comparison is valid, report `improvement observed`, `difference unclear`, or `regression observed` with the evidence. Do not adopt a candidate that introduces a new miss on a required case, breaks explicit invocation, or violates the scope of a request. Even after every evaluation passes, applying the change belongs to the `gadoc-trim` skill and a person's approval.
