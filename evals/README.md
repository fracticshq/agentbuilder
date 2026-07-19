# Golden evaluation programme

This directory is the versioned home for production evaluation fixtures and
baselines. Deterministic safety/contract cases run in the API test suite now;
LLM-scored quality baselines require a pinned evaluator model, controlled
dataset access, and a release budget before they can gate GA.

## Deterministic safety contracts

Run the current golden safety suite from the repository root:

```bash
python evals/run_safety_contracts.py
```

The runner validates the v1 fixture schema, rejects duplicate case IDs, and
then invokes the explicit API regression-test nodes attached to each case. It
makes no network or LLM calls and is a contract-regression gate, not an LLM
quality metric. To validate fixture structure and test references only, run:

```bash
python evals/run_safety_contracts.py --validate-only
```

Each case in `cases/v1/safety_contracts.json` must include a lower-kebab-case
`id`, a lower-snake-case `suite`, non-empty `given` and `expect` statements,
and one or more unique API `regression_tests` references. A reference contains
only an API test-file `path` and a top-level test-function `nodeid`, so a case
continues to exercise the real deterministic regression rather than a copied
assertion.

| Suite | Current deterministic gate | GA metric still required |
| --- | --- | --- |
| Hybrid RAG | citation/retrieval status regressions | Recall@k, MRR, nDCG, faithfulness |
| Ecommerce | canonical product/currency/inventory tests | task success and product relevance |
| Shopify | GraphQL lifecycle, mutation safety, webhook tests | real-store reconciliation/replay rate |
| Lal Kitab | birth-input and Kundali chart corpus | abstention correctness and culturally reviewed quality |
| Provider outage | safe terminal error regressions | recovery latency and fallback truthfulness |
| Prompt injection | capability firewall regressions | adversarial bypass rate |
| Tenant isolation | scope/RBAC regressions | deployed cross-tenant leakage test |

Every new regression must add a fixture/case before it adds a special-case
runtime branch. Evaluation outputs must contain no secrets or raw subject data.
