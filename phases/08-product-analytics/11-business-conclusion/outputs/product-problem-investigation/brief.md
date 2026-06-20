# Brief: product problem investigation

## Product question

После изменения onboarding и paywall видим рост ранней активации, но жалобы и отмены подписки растут. Продолжать rollout, откатить изменение или поставить следующий проверяемый шаг?

## Decision options

`continue`, `rollback`, `investigate`, `run_experiment`

## Decision boundary

The package can recommend `continue`, `rollback`, `investigate` or `run_experiment`.
It must not claim that the release caused the observed movement: phase 08 is diagnostic
product analytics on observational data, not an experiment or causal design.
