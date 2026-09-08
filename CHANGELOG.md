# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

## [0.1.0] - 2026-09-08

### Added

- First release.

- B023 escape analysis: decides whether a closure that captures a loop variable
  can still be called after the loop has moved on.
- B006 mutable default analysis: decides whether a shared default is ever
  actually mutated, accounting for the common `items = items or []` rebind and
  for augmented assignment, which mutates a list in place rather than rebinding.
- A third verdict, `CALLEE`, for the cases where the answer depends on a
  function the tool cannot see into. It names that function instead of guessing.
- Call-site analysis for B006. A mutable default can only be corrupted by a
  caller that omits the argument, so warnings that survive the first pass are
  checked against every call site under the path. When all of them pass the
  argument explicitly the verdict becomes `LATENT`: the defect is real and is
  still reported, but nothing in the tree can trigger it today. Anything the
  scan cannot resolve stays at `BITES`, including a `*args` or `**kwargs` splat
  at the call site and the case of no caller at all, which usually means a
  public entry point called from outside the tree.
- `LATENT` does not set a failing exit code. The exit code answers whether
  something can bite today.
- Command line with `--json` input, `--json-out`, `--all` and `--exit-zero`.
