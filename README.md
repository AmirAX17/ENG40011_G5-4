# Live Fact Checker v1.5.0

Start with **LIVE_START_HERE.txt** for the new Enter-to-send GUI and End review.
The earlier comparison GUI remains under File comparison; its documentation follows.

# Version 1.4.0 update - read this first

The two supplied screenshots establish (1) Groq output was truncated and (2) Gemini 2.5 Flash is unavailable to this account. They do not establish clinical model accuracy.

Use **quick** mode, Gemini **gemini-3.8-flash**, low effort and 8192 cap first. Click **Test API** for one tiny generation request before comparing the bundled ultimate_A/B texts. This generation test uses quota/paid tokens if your account is billed. List models only checks inventory; it cannot prove generation access.

Quick mode replaces the previous large one-call extraction output with a compact findings-only schema: status, exact source quote, exact handover quote, explanation and suggestion. Python verifies quote existence and derives line numbers. Multiline quotes are split into original line citations. If a quote appears more than once the first occurrence is shown and ambiguity is recorded. Exact evidence proves existence, not interpretation or completeness. A source correction is interpreted by the model using the complete text and supporting correction quote; quick mode does not construct a separate supersession graph. It also does not run the detailed extracted-subject, number/unit/certainty guards. The Evidence & history tab explicitly describes this limitation. Report facts are cited-evidence rows with unknown polarity/certainty metadata, not independently extracted semantic facts. Use detailed mode when you need the older extraction/history pipeline, at the cost of longer output and more calls.

A truncated quick response is rejected, then retried once with compact-output feedback at the SAME cap, provider and model. No automatic increase of paid token budget and no paid model fallback. If the second result is incomplete it fails with an explicit error; do not present partial results. Long source/handover text is not silently chopped up or truncated. Quota limits can still prevent even one request; quick mode reduces output but does not bypass them. GPT-OSS effort none maps to low because that model does not support disabling reasoning; online Qwen supports none. Hidden reasoning can still consume output budget even when it is not displayed.

Gemini now uses POST /v1beta/interactions with system_instruction, input, response_format, generation_config, store=false and model_output steps. Default model is gemini-3.8-flash. Older 2.5 presets are removed. Access/free eligibility is still account-specific. Choose a model actually available to your account. No automatic model substitution occurs. Neither HTTP 404 nor 429 is retried. Rate limits, credit balances and model permissions must be resolved with the provider, not by changing a validator.

62 automated mock/validator tests pass, including the exact two error classes, new Gemini request/response fixtures, compact retry, refusal of repeated truncation, evidence rejection and cancellation. No live provider call was made here because your API keys are not available. Actual latency and accuracy remain unmeasured. GUI import/compilation are checked; native GUI rendering and Windows execution remain unverified here. The old screenshots were used to identify failure classes, not to claim a full live reproduction.

The ultimate test pair and expected issues are in model_tests/. Exact row counts vary. Wrong-name ambiguity can legitimately affect attribution; try a second run with matching name spelling to isolate the factual changes.

## Earlier setup and comparison guide (updated where applicable)

# Text Fact Checker - multi-model edition 1.4.0

## What is included
One Python/Tkinter app with fixed official endpoints for Google Gemini, Groq, OpenAI and Anthropic Claude, plus local Ollama. Free and paid tiers use the same provider API; the app cannot determine whether your account is billed. It never upgrades a plan or falls back to a paid provider. Availability, quotas and prices are provider-controlled. Presets are candidates, not an accuracy ranking or a guarantee of access. The editable model box and Check / list models allow account-specific models. Claude presets include older aliases that may need replacement from your model inventory. Gemma/Qwen weights must be downloaded separately for offline use. Paying for a local UI does not improve model accuracy.

The app uses only Python's standard library. It compares text; there is no microphone component. Install Python with Tcl/Tk, extract the folder and run `py -3 main.py` in VS Code, or double-click start_windows.bat. On macOS/Linux use `python3 main.py`; Linux may require python3-tk. Keys, accounts and model downloads are not bundled.

## Provider setup
- **Gemini:** obtain a key from https://aistudio.google.com/api-keys . Select Google Gemini and begin with gemini-3.8-flash or another available Flash model. Free tier eligibility and quota vary. Enabling paid billing can charge requests. Use fictitious data, particularly with free-tier provider data policies.
- **Groq:** https://console.groq.com/keys . Try openai/gpt-oss-120b or openai/gpt-oss-20b. Free token-per-minute restrictions can block large structured outputs even with few requests. Large model size does not establish accuracy on your task.
- **OpenAI:** https://platform.openai.com/api-keys . Set up API billing separately from ChatGPT Plus. Presets include gpt-6-luna, gpt-5.4-mini, gpt-6-sol and gpt-6.1-sol; use account-available IDs. Check current pricing on https://developers.openai.com/api/docs/pricing . The app does not calculate or enforce provider billing limits.
- **Claude:** https://platform.claude.com/settings/keys . Requires funded Anthropic API access separately from a Claude chat subscription. Select an available model from inventory. The adapter uses a forced structured tool response; it does not execute tools or access external data.
- **Ollama:** install the runtime and run e.g. `ollama pull qwen3.5:4b`. Select Ollama and the exact tag. No API key is used. Endpoint is loopback only. On your RTX 2060, a model's full GPU residency and context allocation matter; model size alone does not predict runtime.

Paste a separate key for each provider in the masked field; the app remembers provider keys in memory for this session only. Environment variables are also supported: GEMINI_API_KEY, GROQ_API_KEY, OPENAI_API_KEY, ANTHROPIC_API_KEY. Never put keys in exported reports or share them. The code fixes endpoints and refuses HTTP redirects for online credentials. Only the selected provider receives your inputs; selecting or checking a model inventories it but does not send the input paragraphs. A listed model may still require generation permission, billing or quota.

## Comparing models fairly
1. Use exactly the same A/B text and the same quick/detailed mode for every candidate. Preserve all corrections, names, negations, doses and times.
2. Set a comparable output cap/reasoning level. Provider settings are not mathematically equivalent; record them. Ollama retains temperature 0, seed 42, 16,384 context and 6,000 output cap from the local prototype; GUI output/reasoning controls apply to online adapters, not Ollama.
3. Click Compare once per selected model. No batch is launched automatically. Each click can incur online API costs or use quota.
4. The Model comparison log records provider/model, elapsed time, mode, outcome, counts and an input hash. Identical hash identifies identical inputs. Successful reports can be reopened by double-click. Failed runs remain visible; cancelled runs are not logged as completed comparisons.
5. Export the CSV. It includes reasoning setting, configured output cap, observed tokens where supplied and a blank human_quality_notes column. API-specific thinking/caching reporting differs; logged tokens are not a bill. No price estimate is implied. CSV does not contain input paragraphs, but errors may include provider-returned snippets. JSON/HTML reports contain complete input text and evidence.
6. Compare findings against expected facts. A model with fewer flags is not necessarily better. Record missed contradictions/omissions (false negatives), incorrect flags (false positives), wrong citations, uncertainty errors, failed runs and duration. Evaluate several fresh cases and repeat runs before choosing. No clinical accuracy percentage is claimed.
7. Close the app only after exporting needed results. Run history and keys are not saved automatically. New comparison clears current input/results but leaves the session comparison log available; close app to clear all in-memory history/keys.

## Legacy fast and detailed modes
**Fast** generates source facts, handover facts and comparison findings together, normally in one request. Python validates exact quotes, line numbers, correction links and result references. There is at most one full validation retry. A one-call result can be less accurate or too large for the output cap; fewer calls is not a measured speed guarantee.

**Detailed** extracts each text separately and then compares active facts. Valid extractions are retained during one comparison validation retry. Each extraction may retry once. After a persistent omission/addition label error with both valid evidence sets, the affected finding is AMBIGUOUS with a reason, rather than dropping citations or falsely claiming absence. Other invalid references/evidence still reject the result.

Groq can make one JSON-mode compatibility retry for specific strict schema-generation error codes. Python validation remains in force. This is explicitly recorded in call notes. HTTP 400 otherwise shows provider error/code with the current key redacted. HTTP 429 never triggers an automatic long wait. It can require trying later, reducing a complete input, or changing your account limits. Provider errors are not proof that the model is bad at comparing facts.

Output cap defaults to 8,192 tokens online. This is a ceiling, not a guaranteed allocation or cost. Increase it for long outputs only within model/account limits. Thinking/reasoning may consume the same budget. Some free quotas are smaller than the combined request reservation, so a higher cap can itself cause rejection. Refused or truncated results are rejected. No input is silently truncated. Inputs remain limited to 6,000 characters, 100 KB files, and 60 extracted facts per document; split scenarios only at complete boundaries that preserve corrections.

## Transcription and the seven labels
The same labels remain MATCH, CONTRADICTION, OMITTED, UNSUPPORTED_ADDITION, UNCERTAINTY_CHANGED, TEMPORAL_CHANGE and AMBIGUOUS. An obvious typo like penuts/peanuts may match with clear context. Arif/Aref, penum/peanut and vest/chest can be possible transcription variants, but should be AMBIGUOUS with a suggested interpretation and request for confirmation. There is no new guaranteed phonetic decoder: this is prompted model behaviour and can fail. Original quotes are preserved. Different names, similar drugs/conditions, negation, numerical doses or allergies must not be silently merged. The app does not hear the original audio. The source conversation is a reference, not established clinical truth.

## Run examples and CLI
Small labelled cases are in model_tests/. For a larger test, paste the source/handover paragraphs from your demo, inspect each row and export both JSON and CSV.

GUI: `py -3 main.py` (quick mode is the new default)

CLI (set the provider environment key privately first):
`py -3 main.py --provider gemini --model gemini-3.8-flash --mode quick --source model_tests/01_same_A.txt --handover model_tests/01_same_B.txt --output gemini_run.json`

Change `--provider` to openai, groq, anthropic or ollama and set the corresponding model. Optional `--max-output 8192` and `--reasoning low`. Do not pass a key on the command line. Both compare_files and compare_texts also accept `mode='quick'`, legacy `mode='fast'`, or `mode='detailed'`; library calls default to detailed for compatibility, GUI/CLI default to quick.

## Files and verification
main.py is GUI/CLI entry; factcheck/providers.py is the new multi-provider adapter and preset catalogue; client.py is Ollama; groq_client.py remains as the legacy 1.2 adapter for compatibility/tests (new GUI/CLI uses providers.py); core.py contains evidence/history/comparison validation and both modes; prompts.py contains semantic/transcription instructions; schemas.py defines JSON; gui.py contains the interface and in-memory run log; report.py exports JSON/HTML; tests/ contains mock/validator checks. requirements.txt documents no pip packages. evaluate.py is the older local-only 20-case benchmark and does not compare all providers.

62 automated tests pass, including all previous regressions, request/response fixtures for the four online providers, safe error handling, Groq fallback, one-call processing, fake-evidence rejection and cancellation. No live provider tests have been run here (no user keys available), so this release is not an end-to-end accuracy or latency validation. The GUI imports and compiles; native rendering is not verified in this headless environment. Windows launch requires your local Python/Tkinter installation. Test on the demo computer before presenting.

Official implementation references: https://developers.openai.com/api/docs/guides/structured-outputs ; https://ai.google.dev/api/generate-content ; https://console.groq.com/docs/structured-outputs ; https://platform.claude.com/docs/en/claude_api_primer . Check current provider documentation for model retirement, quotas, billing and data handling.
