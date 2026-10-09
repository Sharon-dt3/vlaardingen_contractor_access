[CodeWiki](../index.md) / [Artifacts](index.md)

# Batch 8 Final Acceptance

## Acceptance Disposition

Batch 8 final acceptance is approved based on the verified validation results recorded for the API, host, clean-room Compose, isolated end-to-end, and focused manager walkthrough checks. The final manager walkthrough passed at both required viewport ranges in a fresh isolated Compose project, and that project was removed after evidence capture.

This record is intentionally bounded to confirmed outcomes, retained evidence locations, known limitations, and repeatable isolated validation guidance. It does not reconstruct, access, or modify any implementation-plan artifact.

## Confirmed Validation Results

| Validation area | Confirmed result |
| --- | --- |
| Batch 8 API acceptance matrix | Passed 4 of 4 checks. |
| Host API suite | Passed 19 of 19 checks. |
| Clean-room Compose lifecycle | Two clean-room migrate, seed, reset, reseed, and health cycles passed. |
| Frontend quality checks | Frontend lint and typecheck completed cleanly. |
| Source-only secret scan | The bounded source-only scan completed cleanly. |
| Isolated connected E2E suite | Passed 21 of 21 tests in 50.1 seconds. The suite covered lifecycle behavior, denial scenarios, role authorization and navigation, and a double reset/reseed sequence. |
| Focused manager walkthrough | Passed 2 of 2 tests in a fresh isolated Compose project. The desktop scenario completed in 7.3 seconds and the tablet scenario completed in 4.0 seconds. |

The automated coverage aligns with the project acceptance contract's Batch 8 ownership of complete automated coverage, final documentation, and clean-room acceptance. The acceptance contract also defines the manager walkthrough as the desktop and tablet inspection of permissions, copy, and failure states.

## Manager Walkthrough Coverage

At a 1440 by 900 desktop viewport, the verified manager scenario confirmed the authenticated manager context, manager-permitted navigation, absence of the disallowed Gate kiosk and Settings links, the expiry-control workspace, and a successful server response to the permitted expiry-processing command. The user-facing completion feedback was displayed only after the request to the authoritative expiry endpoint succeeded.

At a 1023 by 800 tablet viewport, the verified scenario confirmed that the primary-navigation dialog opened, initially focused its close control, exposed permitted links, omitted the disallowed Gate kiosk and Settings links, closed with Escape, and restored focus to the navigation trigger. The focused walkthrough source resets the seeded baseline before and after each test so that each scenario begins and ends at the deterministic state.

## Retained Evidence

The retained Playwright report is available at [`artifacts/batch8/playwright/report/index.html`](../../../artifacts/batch8/playwright/report/index.html). Playwright is configured to write its HTML report to that location without opening it automatically.

The configured retained test-result location is [`artifacts/batch8/playwright/test-results/`](../../../artifacts/batch8/playwright/test-results/). The test configuration records screenshots and traces only when a test fails; therefore, the directory is an output location rather than proof that a passing run generated failure attachments.

The focused manager walkthrough is defined in [`tests/e2e/test_manager_walkthrough.spec.ts`](../../../tests/e2e/test_manager_walkthrough.spec.ts). Its source corroborates the desktop permission and server-feedback assertions, as well as the tablet dialog, Escape, and focus-restoration assertions reported by the verified run.

## Isolated Run and Reset Guidance

Run the final E2E suite only through the disposable Compose `e2e` profile and a fresh isolated Compose project. The profile supplies the internal web and API base URLs, starts the private baseline runner without a host port, and provides the baseline token only to the E2E runner. Do not expose the baseline service or use its reset capability outside this isolated validation topology.

Within the configured E2E container, the confirmed test command is:

```sh
npm ci --prefix tests/e2e --ignore-scripts && npm --prefix tests/e2e test
```

The suite restores its deterministic baseline before and after each mutating manager walkthrough test. That reset requires the private baseline URL and capability token, restores the seed through the baseline runner, and then verifies the public seeded demo health contract. Do not substitute ad hoc data mutation while the suite is running.

After evidence has been captured, remove the isolated Compose project and its disposable volumes from the same project context:

```powershell
docker compose down -v --remove-orphans
```

This cleanup is destructive for the selected Compose project's application state. It is appropriate for the isolated acceptance project that was created for this validation, but it must not be used against a development project that contains useful demo state.

## Known Limitation

The E2E dependency installation reports two high-severity advisories in the Playwright dependency chain: `GHSA-7mvr-c777-76hp`. The current pinned Playwright version is `1.49.1`, and the upstream fixed version is reported as `1.55.1` or later.

No dependency change was made as part of Batch 8 acceptance. This limitation remains outstanding and should be addressed through a separately scoped dependency-update and regression-validation activity.

## Scope Boundary

This acceptance record reports only the verified Batch 8 results listed above. It does not claim additional test coverage from the presence of a report directory, does not retain the removed isolated Compose project as a runtime environment, and does not alter any unavailable implementation-plan document.
