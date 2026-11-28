# Run-Ending Event and 0.261.490 Run Findings Fix

Fixed in version: **0.261.493**

Nine changes from the run on 0.261.490: one error that affected every run, three findings that
now go back to the model that can correct them, a tokenizer declaration in the model catalog,
and five places where a failure did not record its cause.

No prompt, tool description or instruction text was changed. Where a model is now told more,
it is told in the typed finding it already receives.

## 1. Every run ended with an error after its answer was saved

### Issue

On 0.261.490 every harness run logged
`[ORCHESTRATION_RUNS] Headless message publication was not confirmed.` with a `TypeError`
(225 of 225 run endings, pauses included). The run's answer was saved and its outcome recorded
as completed. The client that started the run was then sent an error event and a final event
saying the run failed and its message was not saved.

### Root cause

The answer model's metadata is spread into the final event as keyword arguments. Model-scope
work merged between 0.261.482 and 0.261.490 added `model_scope_type` and `model_scope_id` to
that metadata. `build_run_done_event` did not take them, so the call raised after the run was
already closed.

No test ran a finalization with a scoped answer model, and no test tied the metadata's fields
to the event's arguments.

### Change

- `functions_orchestration_events.py`: `build_run_done_event` takes `model_scope_type` and
  `model_scope_id` and carries them, as the saved message already does.

Not changed: when an error is raised after a run is closed, `_finish` still reports the run to
its client as failed although the saved record says otherwise. That is what turned one missing
argument into a failure shown for every answer. It is recorded as open item 34.

## 2. A calculation program that failed its schema was told only "schema"

### Issue

46 findings in the run were `relational_spec_invalid` with check `schema`. 28 of them repeated
the finding the author already held, and 13 calculation steps ended on it.

### Root cause

`normalize_relational_spec` asked the validator only whether the program was valid and
discarded its error. The author received `category: relational_spec_invalid, check: schema,
step_index: 0` and nothing about where. The planner's path already located schema errors with
`schema_error_location`; the calculation's path did not use it.

### Change

- `functions_tabular_relational.py`: every departure from the schema is located by
  `schema_error_location`. The first, in program order, becomes the failure's detail
  (`schema_keyword`, `schema_problem_count`, and the step's index and operation when it is in a
  step). Up to eight go back to the author in `rejection.feedback.schema_problems`, each with
  the failed keyword, the property path, the operation the step names and what the schema
  allows there.
- A property the author invented is counted, never named: the located values are the schema's
  own names.

A step with several faults in the operation it names reports the most specific one; the next
appears after that one is corrected.

## 3. An action whose model called no function ended its step

### Issue

Two prompts failed with `action_results_missing`: the action's model replied once, in prose,
and started no function call.

### Change

- `functions_orchestration_actions.py`: a reply that starts no function call is returned to
  the action's model once, as data: `error_code: action_function_call_missing`,
  `validation_rule: function_call_required`, the functions it was offered and the number of
  bound documents. The model's own reply stays in the history. A second reply without a call
  ends the step as before, with `call_finding_count: 1` in its record.
- This costs one more model call per occurrence. The model's budget is checked again before it.

Not changed: a step whose calls started and returned nothing still ends.

## 4. Request size was counted in bytes for models the tokenizer library did not know

### Issue

Two answer steps ended `result_input_too_large`. The sizes logged from 0.261.490 show both
were counted with `utf8_upper_bound`: 1,060,988 and 3,908,035 bytes, compared with an input
budget of 903,560 tokens.

### Root cause

The budget asks the installed tokenizer library for the model's encoding by name. The
installed version (tiktoken 0.12.0) resolves `gpt-5` and names beginning `gpt-5-`, and not
`gpt-5.4` or `gpt-5.6-sol`. A bounded model with no known tokenizer is counted in UTF-8 bytes,
which is several times its token count for ordinary text.

### Change

- `model_capabilities.json`: 33 OpenAI text records declare `tokenizer` (`o200k_base`), each
  with verified evidence. The source is OpenAI's tiktoken model table as published for v0.14.0,
  which resolves every model name beginning `gpt-5` to `o200k_base`. The encodings were taken by
  applying that table to each record's id: an exact name first, then the first prefix.
- `model_capabilities.schema.json`: `tokenizer` is an optional field of a token model record.
  A declaration needs verified evidence on the record; evidence without a declaration is
  refused; a hosting profile cannot carry one. `schemaVersion` stays 4, and a catalog without
  the field is still valid.
- `functions_model_capabilities.py`: `resolve_model_tokenizer` returns the declared encoding
  for the exact model, matched the way numeric limits are: the record's id or a verified alias.
- `functions_workflow_context.py`: the budget reads the catalog's declaration first. A model
  the catalog does not declare is looked up in the library as before. The audit records where
  the encoding came from (`token_estimator_source`: `catalog`, `library` or `none`).

Not declared: `gpt-chat-latest`, which the table does not resolve, and every non-OpenAI model.
Those keep the byte bound. The same request of 252,054 bytes is 44,031 tokens for `gpt-5.4`
under `o200k_base`.

A deployment that has installed a signed catalog update keeps that catalog until a new one is
published. A published catalog that uses the field needs `minimumAppVersion` 0.261.493.

Not changed: `functions_context_usage.py` looks up its own encoding from the library and does
not read the catalog.

## 5. A file step that failed before rendering recorded no cause

### Issue

One prompt ended `step_failed` on `render_file`, on both attempts, with no record of why. A
render attempt reports itself; a step that fails before one had nothing.

### Change

- `functions_orchestration_rendering.py`: a failed result carries a diagnostic for the step
  owner: the error's type, its closed code and whether an output record existed.
- `functions_orchestration_executor.py`: the owner logs
  `[ORCHESTRATION_EXECUTOR] A file step did not produce its file.` with the output's code,
  whether it is retryable, the output's state and format, and that diagnostic. The diagnostic
  is removed from the result before it is validated or saved.

This explains the next occurrence. The cause of the one in the run is not known.

## 6. An aggregate that met a non-numeric value named the first value only

### Issue

The largest single cause in the run: 45 findings and 18 ended steps. The author was told a
value in the measure was not a number, as `string`, and did not correct it.

### Change

- `functions_tabular_transformations.py`: the finding carries the value's kind by the
  calculation's own reading (`text`, `comma_decimal_text`, `date_text`, `blank`, ...) and, for
  an aggregate, how many of the measure's values cannot be read and how many there are. One
  stray cell and a whole column of text are different faults.
- The detail is what is logged and what the author is given, so the author now receives the
  same three facts. No cell value is carried.

## 7. A request refused at planning recorded only its last refusal

### Change

- `functions_orchestration_planner.py`: the final record says how many attempts were corrected,
  what the first and the previous were refused for, whether the last refusal repeats the
  previous one, how many distinct refusals there were, and where the refusal was raised
  (`error_site`). Each correction record says whether it repeats the one before and where it
  was raised. A refusal with no named rule can now be found by its site.

## 8. A completeness report with a rejected answer quote did not say which or why

### Change

- `functions_task_completeness.py`: `completeness_candidate_reference_invalid` carries its
  rule (`answer_quote_not_in_candidate` or `answer_quote_missing`), the judgment's position,
  the number of judgments and the lengths of the quote and the answer. These reach the log and,
  because the checker's repair request is built from the same details, the checker.

## 9. A refused question to the user did not record which condition refused it

### Issue

Outside the harness, an agent's answer ended `stream_failed` with no content when the agent
called the ask-the-user function. Every refusal raises the same message, and its code was not
logged. No question was opened successfully in the five days of telemetry read.

### Change

- `agent_interaction_contracts.py`, `functions_user_input.py`,
  `functions_action_credential_runtime.py`: each refusal names its rule (for example
  `user_input_not_enabled`, `tool_call_id_missing`, `specification_not_json`,
  `requested_schema_invalid`, `saved_request_specification_differs`).
- `user_input_plugin.py`: one record,
  `[USER_INPUT] An agent's question to the user could not be opened.`, with the code, the rule,
  the status and where it was raised.

Not fixed: which condition refused the questions in the run is not known. Typical question
specifications pass the validator, so a condition of the request is as likely as the
specification. One candidate, not verified: the function is added to an agent's kernel when a
run may ask the user and is never removed, so a later run of the same kernel that may not ask
still offers it.

## Files modified

- `application/single_app/functions_orchestration_events.py`
- `application/single_app/functions_tabular_relational.py`
- `application/single_app/functions_tabular_transformations.py`
- `application/single_app/functions_orchestration_actions.py`
- `application/single_app/functions_model_capabilities.py`
- `application/single_app/functions_workflow_context.py`
- `application/single_app/functions_workflow_policy_errors.py`
- `application/single_app/functions_orchestration_rendering.py`
- `application/single_app/functions_orchestration_executor.py`
- `application/single_app/functions_orchestration_planner.py`
- `application/single_app/functions_task_completeness.py`
- `application/single_app/agent_interaction_contracts.py`
- `application/single_app/functions_user_input.py`
- `application/single_app/functions_action_credential_runtime.py`
- `application/single_app/semantic_kernel_plugins/user_input_plugin.py`
- `application/single_app/functions_appinsights.py` (code keys for the new fields)
- `application/single_app/static/json/model_capabilities.json`
- `application/single_app/static/json/schemas/model_capabilities.schema.json`
- `application/single_app/config.py`
- `functional_tests/cosmos_response_boundaries.json` (one owner re-reviewed; its body is
  unchanged)
- Nine test files under `functional_tests/`, listed below.

## Validation

- `test_orchestration_harness_execution.py`: a run whose answer model has a scope ends with
  its saved answer and carries the scope; every field the model's metadata can return is an
  argument of the final event. Both fail on the previous code. A file step that fails before
  any render attempt logs its cause, and the diagnostic is not saved.
- `test_tabular_relational_calculations.py`: a program with three schema faults reports each
  with its location and none of the author's own text; twelve faults return eight. An aggregate
  over a stray text cell, a column of text, decimal-comma cells, a date column and blank cells
  reports the kind and the counts.
- `test_orchestration_relational_results.py`: through the real authoring loop, a schema fault
  is returned with its location and corrected on the second call.
- `test_orchestration_document_loader_reliability.py`: through the real HTTP path, a reply
  with no call is returned once and the model then reads the document and the step completes;
  a second reply without a call ends the step with the finding counted.
- `test_model_catalog_token_evidence.py`: the declared tokenizers are exactly what the
  published table resolves; each has verified evidence and loads; nothing is declared for a
  model the table does not resolve; a declaration without evidence, evidence without a
  declaration, unverified evidence, an unknown encoding and a profile carrying one are refused.
- `test_workflow_context_budget.py`: a `gpt-5.4` request is sized with `o200k_base` from the
  catalog, at less than a quarter of its byte size; a model with no declaration keeps the byte
  bound.
- `test_orchestration_planner_failure_diagnostics.py`, `test_task_completeness_engine.py`,
  `test_guided_user_input.py`: the new record fields.
- `scripts/check_cosmos_response_boundaries.py`: 0 review gaps.

Before: every run's client was told the run failed; a schema fault said "schema"; an action
with no call ended; a `gpt-5.4` request was sized in bytes.
After: the final event is built; a schema fault says where; the action's model is told once;
the request is sized in tokens.

Not run against the deployed application. What a browser shows for the final event was read
from the code, not observed.
