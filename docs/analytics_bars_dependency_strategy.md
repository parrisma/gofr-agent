# Analytics Bars Dependency Strategy

Status: Resolved and superseded for descriptor-enabled workflows by the results
hub handoff implementation. The strategy remains as historical context for the
pre-hub `bars` argument failure mode.

## Symptom

During fixture chat runs, the model calls analytics tools such as `simple_return`,
`historical_volatility`, and `max_drawdown` with `ticker` and date arguments but
without the required `bars` argument. Downstream validation then fails with
Pydantic `Field required` errors for `bars`.

## Hypothesised Root Cause

The agent prompt currently lists only tool names and free-form descriptions.
That leaves cross-tool input dependencies implicit, especially for analytics
tools that require OHLCV `bars` fetched first from
`instruments__get_ohlcv_history`.

## Assumptions And Validation

- Assumption: the analytics tool signatures are correct and should continue to
  require agent-supplied `bars`.
- Assumption: the model is more likely to compose the correct tool sequence when
  the prompt surfaces required arguments and dependency hints.
- Validation: add a focused unit test proving the generated system prompt
  includes required arguments from the tool schema, including `bars`.
- Validation: run the touched unit tests for system prompt generation and the
  fixture chat wrapper.

## Diagnostics Order

1. Confirm analytics fixture tools require `bars` and do not accept date ranges.
2. Confirm the current system prompt omits required-argument details.
3. Patch prompt generation to surface required arguments and a `bars` dependency
   hint.
4. Clarify analytics tool docstrings so the function/tool description reinforces
   the same workflow.
5. Run focused tests for the changed slice.