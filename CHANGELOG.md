# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- B023 escape analysis: decides whether a closure that captures a loop variable
  can still be called after the loop has moved on.
- B006 mutable default analysis: decides whether a shared default is ever
  actually mutated, accounting for the common `items = items or []` rebind and
  for augmented assignment, which mutates a list in place rather than rebinding.
- A third verdict, `CALLEE`, for the cases where the answer depends on a
  function the tool cannot see into. It names that function instead of guessing.
- Command line with `--json` input, `--json-out`, `--all` and `--exit-zero`.
