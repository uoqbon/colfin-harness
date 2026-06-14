---
name: Feature request
about: Suggest an idea or enhancement
title: "[Feature] "
labels: enhancement
assignees: ''
---

> ⚠️ Please keep the project's safety contract in mind: the harness **must never submit,
> modify, or cancel an order**, the model is **locked to the Google Gemma family on MLX**,
> and **no credentials** live in code/config/env. Feature requests that would weaken these
> invariants will be declined. See [CONTRIBUTING.md](../../CONTRIBUTING.md).

## Problem / motivation

What problem are you trying to solve? Why is it valuable?

## Proposed solution

A clear and concise description of what you want to happen.

## Alternatives considered

Any alternative solutions or features you've considered.

## Safety check

- [ ] This request does **not** introduce an order-submission path, bypass, or
      `confirmed=True` flow.
- [ ] This request does **not** weaken the model-family lock or the credential-handling
      rules.

## Additional context

Anything else, such as mockups, links, or references.
