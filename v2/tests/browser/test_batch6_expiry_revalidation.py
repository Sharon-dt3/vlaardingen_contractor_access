#!/usr/bin/env python3
"""Durable browser validation for the Batch 6 expiry and re-validation lifecycle.

Run from the repository root after the local Compose application is healthy:

    python tests/browser/test_batch6_expiry_revalidation.py

The validation resets and seeds the local demo, signs in through the rendered
manager workspace, and retains a failure-safe artifact bundle under
``artifacts/batch6/``. It proves that Sofia's seeded expired VCA evidence blocks
backend compliance, then uses only published APIs in the authenticated browser
session to attach, extract, verify, and complete a replacement renewal. Finally,
it confirms restored authoritative eligibility and an existing Batch 4 gate grant.

Every browser stage persists a screenshot, HTML, current URL, visible body text,
console messages, and failed-network metadata. Failure artifacts are therefore
available even when Selenium times out before a rendered assertion completes.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import time
import traceback
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, TypeVar

try:
    from selenium import webdriver
    from selenium.common.exceptions import TimeoutException, WebDriverException
    from selenium.webdriver import ChromeOptions
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.common.by import By
    from selenium.webdriver.remote.webdriver import WebDriver
    from selenium.webdriver.support import expected_conditions as expected
    from selenium.webdriver.support.ui import WebDriverWait
except ImportError as error:  # pragma: no cover - execution environment guard
    raise SystemExit(
        "Batch 6 browser validation requires Selenium in the execution environment."
    ) from error


STAGE_PREFIX = "[BATCH-6]"
DEFAULT_WEB_BASE_URL = os.environ.get("BATCH6_WEB_BASE_URL", "http://localhost:3000")
DEFAULT_API_BASE_URL = os.environ.get("BATCH6_API_BASE_URL", "http://localhost:8000")
DEMO_HANDLE = os.environ.get("BATCH6_DEMO_HANDLE", "admin.demo")
DEMO_PASSWORD = os.environ.get("BATCH6_DEMO_PASSWORD", "renewi-demo-access")
SHORT_WAIT_SECONDS = int(os.environ.get("BATCH6_SHORT_WAIT_SECONDS", "20"))
LONG_WAIT_SECONDS = int(os.environ.get("BATCH6_LONG_WAIT_SECONDS", "60"))
T = TypeVar("T")


@dataclass
class ValidationState:
    """Keep identifiers and browser diagnostic context for one validation run."""

    artifact_directory: Path
    web_base_url: str
    api_base_url: str
    driver: WebDriver | None = None
    stage_number: int = 0
    last_selector: str | None = None
    site_id: str | None = None
    sofia_id: str | None = None
    sofia_visit_id: str | None = None
    invitation_id: str | None = None
    task_id: str | None = None
    renewal_evidence_id: str | None = None
    trace: list[dict[str, Any]] = field(default_factory=list)


class Batch6BrowserValidation:
    """Exercise the rendered manager workspace and authoritative Batch 6 lifecycle."""

    def __init__(
        self,
        *,
        artifact_root: Path,
        web_base_url: str,
        api_base_url: str,
        headless: bool,
    ) -> None:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        artifact_directory = artifact_root / f"run-{timestamp}-{os.urandom(4).hex()}"
        artifact_directory.mkdir(parents=True, exist_ok=True)
        self.state = ValidationState(
            artifact_directory=artifact_directory,
            web_base_url=web_base_url.rstrip("/"),
            api_base_url=api_base_url.rstrip("/"),
        )
        self.headless = headless
        self.logger = logging.getLogger("batch6.browser")
        self._write_json(
            "run_configuration.json",
            {
                "web_base_url": self.state.web_base_url,
                "api_base_url": self.state.api_base_url,
                "headless": headless,
                "demo_handle": DEMO_HANDLE,
            },
        )

    # PUBLIC_INTERFACE
    def run(self) -> None:
        """Run one clean Batch 6 lifecycle and restore the seed baseline afterward."""

        workflow_error: BaseException | None = None
        cleanup_error: BaseException | None = None
        try:
            self.reset_baseline("prepare_baseline")
            self.state.driver = self._create_driver()
            self._run_stage("login-and-workspace", self.login_and_verify_workspace)
            self._run_stage("expired-compliance-denial", self.assert_expired_denial)
            self._run_stage("expiry-task-creation", self.create_expiry_task)
            self._run_stage("verified-vca-renewal", self.create_verified_renewal)
            self._run_stage("complete-revalidation", self.complete_revalidation)
            self._run_stage(
                "restored-eligibility-and-gate-grant",
                self.assert_restored_eligibility_and_gate_grant,
            )
            self._run_stage(
                "ordered-audit-lifecycle",
                self.assert_ordered_audit_lifecycle,
            )
            self._run_stage(
                "rendered-completed-workspace",
                self.assert_completed_workspace,
            )
        except BaseException as error:
            workflow_error = error
        finally:
            try:
                self.reset_baseline("reset_baseline")
            except BaseException as error:
                cleanup_error = error
            finally:
                if self.state.driver is not None:
                    self.state.driver.quit()

        if workflow_error is not None:
            if cleanup_error is not None:
                raise RuntimeError(
                    "The Batch 6 lifecycle and deterministic cleanup both failed. "
                    "Inspect the retained artifact bundle before rerunning."
                ) from workflow_error
            raise workflow_error
        if cleanup_error is not None:
            raise cleanup_error

    def login_and_verify_workspace(self) -> None:
        """Sign in through the rendered UI and confirm the API-derived workspace."""

        self._driver.get(f"{self.state.web_base_url}/login")
        handle = self._visible((By.ID, "handle"))
        password = self._visible((By.ID, "password"))
        handle.clear()
        handle.send_keys(DEMO_HANDLE)
        password.clear()
        password.send_keys(DEMO_PASSWORD)
        self._click(
            (By.CSS_SELECTOR, "form button[type='submit']"),
            "rendered login submit button",
        )
        self._wait().until(
            lambda current_driver: "/login" not in current_driver.current_url
        )
        workspace_heading = (
            By.XPATH,
            "//h2[normalize-space()='Expiry control workspace']",
        )
        self._visible(workspace_heading)
        self._write_json(
            "rendered_workspace.json",
            {
                "workspace_heading": "Expiry control workspace",
                "current_url": self._driver.current_url,
            },
        )

    def assert_expired_denial(self) -> None:
        """Record Sofia's current expired compliance state before renewal."""

        self._resolve_sofia()
        compliance = self._api_json(
            f"/api/visits/{self._required(self.state.sofia_visit_id, 'Sofia visit')}/compliance"
        )
        vca_check = self._evidence_check(compliance, "VCA_CERTIFICATE")
        if compliance.get("eligible") is not False or vca_check.get("status") != "expired":
            raise AssertionError(
                "Sofia must be ineligible because her verified VCA evidence is expired: "
                f"{compliance!r}"
            )
        self._write_json(
            "expired_compliance.json",
            {"compliance": compliance, "vca_check": vca_check},
        )

    def create_expiry_task(self) -> None:
        """Process expiry and select Sofia's durable open VCA re-validation task."""

        processed = self._api_json("/api/expiry/process", method="POST")
        tasks = self._api_json("/api/revalidation/tasks")
        sofia_id = self._required(self.state.sofia_id, "Sofia identifier")
        task = next(
            (
                candidate
                for candidate in tasks
                if str(candidate.get("person_id")) == sofia_id
                and candidate.get("status") == "OPEN"
                and candidate.get("source_kind") == "EVIDENCE"
            ),
            None,
        )
        if task is None:
            raise AssertionError(
                "Expiry processing did not return Sofia's open evidence re-validation "
                f"task. Processing result={processed!r}, tasks={tasks!r}"
            )
        self.state.task_id = str(task["id"])
        self._write_json(
            "expiry_task.json",
            {"processing": processed, "task": task},
        )

    def create_verified_renewal(self) -> None:
        """Use the existing published evidence workflow to create a VCA renewal."""

        invitations = self._api_json("/api/invitations")
        sofia_id = self._required(self.state.sofia_id, "Sofia identifier")
        invitation = next(
            (
                candidate
                for candidate in invitations
                if str(candidate.get("person_id")) == sofia_id
                and candidate.get("purpose") == "Synthetic Batch 6 Sofia VCA renewal"
                and candidate.get("status") == "pre_registered"
            ),
            None,
        )
        if invitation is None:
            raise AssertionError(
                "The seeded Sofia renewal invitation was not available through the "
                f"published workflow API: {invitations!r}"
            )
        self.state.invitation_id = str(invitation["id"])

        assets = self._api_json("/api/evidence/assets")
        vca_asset = next(
            (
                asset
                for asset in assets
                if asset.get("evidence_type") == "vca_certificate"
                and asset.get("is_active") is True
            ),
            None,
        )
        if vca_asset is None:
            raise AssertionError("No active synthetic VCA asset was available.")

        attached = self._api_json(
            f"/api/invitations/{self.state.invitation_id}/evidence/assets",
            method="POST",
            body={"asset_id": vca_asset["id"]},
        )
        self.state.renewal_evidence_id = str(attached["id"])
        extracted = self._api_json(
            f"/api/evidence/{self.state.renewal_evidence_id}/extract",
            method="POST",
        )
        verified = self._api_json(
            f"/api/evidence/{self.state.renewal_evidence_id}/verify",
            method="POST",
            body={"reason": "Verified deterministic Batch 6 VCA renewal."},
        )
        if (
            attached.get("status") != "uploaded"
            or extracted.get("status") != "extracted"
            or verified.get("status") != "verified"
            or not verified.get("expiry_date")
        ):
            raise AssertionError(
                "The public evidence workflow did not create a verified current "
                f"renewal: attached={attached!r}, extracted={extracted!r}, "
                f"verified={verified!r}"
            )
        self._write_json(
            "verified_renewal.json",
            {
                "invitation": invitation,
                "asset": vca_asset,
                "attached": attached,
                "extracted": extracted,
                "verified": verified,
            },
        )

    def complete_revalidation(self) -> None:
        """Complete Sofia's task only after the verified replacement exists."""

        task_id = self._required(self.state.task_id, "re-validation task")
        completed = self._api_json(
            f"/api/revalidation/tasks/{task_id}/complete",
            method="POST",
        )
        if completed.get("status") != "COMPLETED" or not completed.get("completed_at"):
            raise AssertionError(
                f"The renewed re-validation task was not completed: {completed!r}"
            )
        self._write_json("completed_task.json", completed)

    def assert_restored_eligibility_and_gate_grant(self) -> None:
        """Prove backend compliance recovery and use the existing Batch 4 gate path."""

        visit_id = self._required(self.state.sofia_visit_id, "Sofia visit")
        site_id = self._required(self.state.site_id, "Vlaardingen site")
        compliance = self._api_json(f"/api/visits/{visit_id}/compliance")
        vca_check = self._evidence_check(compliance, "VCA_CERTIFICATE")
        if compliance.get("eligible") is not True or vca_check.get("status") != "passed":
            raise AssertionError(
                "Backend compliance did not restore after verified renewal: "
                f"{compliance!r}"
            )

        gate = self._api_json(
            "/api/gate/evaluations",
            method="POST",
            body={
                "token_reference": (
                    "renewi-access:demo:sofia:opaque-reference"
                ),
                "site_id": site_id,
                "presentation_reference": "batch6-sofia-renewal-presentation",
            },
        )
        if (
            gate.get("decision") != "GRANT"
            or gate.get("primary_reason_code") != "ACCESS_GRANTED"
        ):
            raise AssertionError(
                "The existing gate pathway did not grant Sofia after backend "
                f"revalidation: {gate!r}"
            )
        self._write_json(
            "restored_eligibility_and_gate_grant.json",
            {"compliance": compliance, "vca_check": vca_check, "gate": gate},
        )

    def assert_ordered_audit_lifecycle(self) -> None:
        """Prove the exercised expiry-to-grant lifecycle is chronological in audit history."""

        sofia_id = self._required(self.state.sofia_id, "Sofia identifier")
        visit_id = self._required(self.state.sofia_visit_id, "Sofia visit")
        task_id = self._required(self.state.task_id, "re-validation task")
        renewal_evidence_id = self._required(
            self.state.renewal_evidence_id,
            "renewal evidence",
        )
        audit_events = self._api_json("/api/audit/events")
        if not isinstance(audit_events, list):
            raise AssertionError(
                f"The audit history did not return a chronological event list: {audit_events!r}"
            )

        def has_person(event: dict[str, Any]) -> bool:
            """Return whether an audit event is tied to Sofia's lifecycle."""

            details = event.get("details")
            return (
                isinstance(details, dict)
                and str(details.get("person_id")) == sofia_id
            )

        required_events: list[tuple[str, Callable[[dict[str, Any]], bool]]] = [
            ("expiry.alert_created", has_person),
            (
                "revalidation.task_created",
                lambda event: (
                    has_person(event) and str(event.get("entity_id")) == task_id
                ),
            ),
            (
                "evidence.verified",
                lambda event: (
                    has_person(event)
                    and str(event.get("entity_id")) == renewal_evidence_id
                ),
            ),
            (
                "revalidation.task_completed",
                lambda event: (
                    has_person(event) and str(event.get("entity_id")) == task_id
                ),
            ),
            (
                "gate.granted",
                lambda event: (
                    has_person(event)
                    and isinstance(event.get("details"), dict)
                    and str(event["details"].get("visit_id")) == visit_id
                ),
            ),
        ]

        matched_events: list[dict[str, Any]] = []
        search_start = 0
        for action, matches_lifecycle in required_events:
            match_index = next(
                (
                    index
                    for index, event in enumerate(audit_events[search_start:], search_start)
                    if isinstance(event, dict)
                    and event.get("action") == action
                    and matches_lifecycle(event)
                ),
                None,
            )
            if match_index is None:
                observed_actions = [
                    str(event.get("action"))
                    for event in audit_events
                    if isinstance(event, dict) and has_person(event)
                ]
                raise AssertionError(
                    f"Required Batch 6 audit action {action!r} was absent after "
                    f"the preceding lifecycle evidence. Observed Sofia actions: "
                    f"{observed_actions!r}"
                )
            matched_events.append(audit_events[match_index])
            search_start = match_index + 1

        completion_details = matched_events[3].get("details")
        if (
            not isinstance(completion_details, dict)
            or completion_details.get("eligibility_by_visit", {}).get(visit_id) is not True
        ):
            raise AssertionError(
                "The re-validation completion audit event did not record restored "
                f"eligibility for Sofia's visit: {matched_events[3]!r}"
            )

        self._write_json(
            "ordered_audit_lifecycle.json",
            {
                "required_actions": [action for action, _ in required_events],
                "matched_events": matched_events,
            },
        )

    def assert_completed_workspace(self) -> None:
        """Refresh the rendered workspace and prove its protected API state updated."""

        self._driver.get(f"{self.state.web_base_url}/")
        completed_status = (
            By.XPATH,
            "//section[@aria-labelledby='revalidation-tasks']"
            "//*[normalize-space()='COMPLETED']",
        )
        self._visible((By.XPATH, "//h2[normalize-space()='Expiry control workspace']"))
        self._visible(completed_status)

    def reset_baseline(self, stage: str) -> None:
        """Reset, seed, and health-check the deterministic local demo baseline."""

        self._log_stage("START", stage)
        cleanup_log = self.state.artifact_directory / "baseline_cleanup.txt"
        try:
            self._run_compose_command(
                ["exec", "-T", "api", "python", "-m", "app.commands", "reset"],
                cleanup_log,
            )
            self._run_compose_command(
                ["exec", "-T", "api", "python", "-m", "app.commands", "seed"],
                cleanup_log,
            )
            health = self._wait_for_healthy_api()
            if health.get("status") != "ready" or health.get("demo_mode") is not True:
                raise AssertionError(f"Demo health was not ready: {health!r}")
            self._write_json(f"{stage}_health.json", health)
        except BaseException:
            self._log_stage("FAIL", stage)
            self._write_text(f"{stage}_error.txt", traceback.format_exc())
            raise
        else:
            self._log_stage("PASS", stage)

    def _resolve_sofia(self) -> None:
        """Resolve Sofia, her active visit, and the one target site via protected APIs."""

        people = self._api_json("/api/people")
        sofia = next(
            (
                person
                for person in people
                if person.get("first_name") == "Sofia"
                and person.get("last_name") == "Janssen"
            ),
            None,
        )
        if sofia is None:
            raise AssertionError("The deterministic Sofia Janssen person was absent.")
        visits = self._api_json("/api/visits")
        visit = next(
            (
                candidate
                for candidate in visits
                if str(candidate.get("person_id")) == str(sofia.get("id"))
                and candidate.get("status") == "active"
            ),
            None,
        )
        if visit is None:
            raise AssertionError("Sofia has no active deterministic visit.")

        self.state.sofia_id = str(sofia["id"])
        self.state.sofia_visit_id = str(visit["id"])
        self.state.site_id = str(visit["site_id"])
        self._write_json(
            "selected_sofia.json",
            {
                "person_id": self.state.sofia_id,
                "visit_id": self.state.sofia_visit_id,
                "site_id": self.state.site_id,
            },
        )

    @property
    def _driver(self) -> WebDriver:
        """Return the initialized browser or fail with a clear lifecycle error."""

        if self.state.driver is None:
            raise RuntimeError("The Chrome driver was not initialized.")
        return self.state.driver

    def _create_driver(self) -> WebDriver:
        """Create a headless-capable Chrome session with console/network diagnostics."""

        options = ChromeOptions()
        if self.headless:
            options.add_argument("--headless=new")
        options.add_argument("--window-size=1440,900")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--no-sandbox")
        options.set_capability(
            "goog:loggingPrefs",
            {"browser": "ALL", "performance": "ALL"},
        )
        chrome_binary = os.environ.get("BATCH6_CHROME_BINARY")
        if chrome_binary:
            options.binary_location = chrome_binary
        driver_path = os.environ.get("BATCH6_CHROMEDRIVER_PATH")
        service = Service(executable_path=driver_path) if driver_path else Service()
        driver = webdriver.Chrome(service=service, options=options)
        driver.set_page_load_timeout(LONG_WAIT_SECONDS)
        return driver

    def _run_stage(self, stage: str, action: Callable[[], T]) -> T:
        """Execute one stage and retain diagnostics on both success and failure."""

        self.state.stage_number += 1
        self._log_stage("START", stage)
        try:
            result = action()
        except BaseException:
            self._log_stage("FAIL", stage)
            self._capture_diagnostics(
                f"{stage}_failure",
                selector=self.state.last_selector,
            )
            raise
        self._capture_diagnostics(stage, selector=self.state.last_selector)
        self._log_stage("PASS", stage)
        return result

    def _api_json(
        self,
        path: str,
        *,
        method: str = "GET",
        body: dict[str, Any] | None = None,
    ) -> Any:
        """Request an API resource through the authenticated rendered browser session."""

        if not path.startswith("/"):
            raise ValueError("Browser API paths must start with '/'.")
        script = """
            const done = arguments[arguments.length - 1];
            const [url, method, body] = arguments;
            const options = {
                method,
                credentials: "include",
                headers: { Accept: "application/json" }
            };
            if (body !== null) {
                options.headers["Content-Type"] = "application/json";
                options.body = JSON.stringify(body);
            }
            fetch(url, options).then(async (response) => {
                const raw = await response.text();
                let payload;
                try {
                    payload = raw ? JSON.parse(raw) : null;
                } catch {
                    payload = raw;
                }
                done({ ok: response.ok, status: response.status, payload });
            }).catch((error) => done({
                ok: false,
                status: 0,
                payload: String(error)
            }));
        """
        response = self._driver.execute_async_script(
            script,
            f"{self.state.api_base_url}{path}",
            method,
            body,
        )
        self.state.trace.append(
            {
                "method": method,
                "path": path,
                "status": response.get("status"),
                "ok": response.get("ok"),
            }
        )
        if not response.get("ok"):
            raise AssertionError(
                f"Authenticated API request {method} {path} failed with HTTP "
                f"{response.get('status')}: {response.get('payload')!r}"
            )
        return response.get("payload")

    def _capture_diagnostics(self, label: str, *, selector: str | None) -> None:
        """Persist URL, body, screenshot, HTML, console, and network diagnostics."""

        driver = self.state.driver
        if driver is None:
            return
        safe_label = label.replace(" ", "_").replace("/", "_")
        prefix = f"{self.state.stage_number:02d}_{safe_label}"
        try:
            driver.save_screenshot(str(self.state.artifact_directory / f"{prefix}.png"))
            self._write_text(f"{prefix}.html", driver.page_source)
            self._write_text(f"{prefix}_url.txt", driver.current_url)
            self._write_text(
                f"{prefix}_visible_text.txt",
                driver.find_element(By.TAG_NAME, "body").text,
            )
            self._write_json(
                f"{prefix}_diagnostics.json",
                {
                    "selector": selector,
                    "current_url": driver.current_url,
                    "stage_trace": self.state.trace,
                    "browser_console": self._browser_console_entries(),
                    "failed_network_requests": self._network_errors(),
                },
            )
        except WebDriverException as error:
            self._write_text(
                f"{prefix}_diagnostic_capture_error.txt",
                f"{type(error).__name__}: {error}",
            )

    def _browser_console_entries(self) -> list[dict[str, Any]]:
        """Return browser console entries without failing diagnostic collection."""

        try:
            return list(self._driver.get_log("browser"))
        except WebDriverException as error:
            return [{"diagnostic_unavailable": str(error)}]

    def _network_errors(self) -> list[dict[str, Any]]:
        """Return failed browser network responses without exposing private payloads."""

        try:
            entries = self._driver.get_log("performance")
        except WebDriverException as error:
            return [{"diagnostic_unavailable": str(error)}]

        failures: list[dict[str, Any]] = []
        for entry in entries:
            try:
                message = json.loads(entry["message"])["message"]
                if message.get("method") != "Network.responseReceived":
                    continue
                response = message.get("params", {}).get("response", {})
                status = response.get("status")
                if isinstance(status, (int, float)) and status >= 400:
                    failures.append(
                        {
                            "status": status,
                            "url": response.get("url"),
                            "status_text": response.get("statusText"),
                        }
                    )
            except (KeyError, TypeError, json.JSONDecodeError):
                continue
        return failures

    def _visible(self, locator: tuple[str, str]) -> Any:
        """Wait for one rendered selector and retain it as diagnostic context."""

        self.state.last_selector = self._selector_text(locator)
        return self._wait().until(expected.visibility_of_element_located(locator))

    def _click(self, locator: tuple[str, str], description: str) -> None:
        """Click one rendered control after it becomes interactable."""

        self.state.last_selector = self._selector_text(locator)
        self._wait().until(expected.element_to_be_clickable(locator)).click()
        self.logger.info("%s Clicked %s", STAGE_PREFIX, description)

    def _wait(self, seconds: int = SHORT_WAIT_SECONDS) -> WebDriverWait:
        """Create a bounded explicit Selenium wait."""

        return WebDriverWait(self._driver, seconds)

    def _run_compose_command(self, arguments: list[str], output_path: Path) -> None:
        """Run one non-interactive baseline command and retain its combined output."""

        result = subprocess.run(
            ["docker", "compose", *arguments],
            cwd=self._project_root(),
            capture_output=True,
            check=False,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        with output_path.open("a", encoding="utf-8", errors="replace") as output:
            output.write(f"\n$ docker compose {' '.join(arguments)}\n")
            output.write(result.stdout)
            output.write(result.stderr)
        if result.returncode != 0:
            raise RuntimeError(
                f"Baseline command failed ({result.returncode}): "
                f"docker compose {' '.join(arguments)}"
            )

    def _wait_for_healthy_api(self) -> dict[str, Any]:
        """Poll the API health endpoint until reset and seed operations are ready."""

        deadline = time.monotonic() + LONG_WAIT_SECONDS
        last_error: BaseException | None = None
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(
                    f"{self.state.api_base_url}/health",
                    timeout=5,
                ) as response:
                    if response.status != 200:
                        raise AssertionError(f"/health returned HTTP {response.status}.")
                    return json.loads(response.read().decode("utf-8", errors="replace"))
            except (
                urllib.error.URLError,
                TimeoutError,
                AssertionError,
                json.JSONDecodeError,
            ) as error:
                last_error = error
                time.sleep(2)
        raise AssertionError(
            "The API did not return healthy after reset and reseed."
        ) from last_error

    @staticmethod
    def _evidence_check(compliance: dict[str, Any], code: str) -> dict[str, Any]:
        """Find one named evidence compliance check or fail with complete context."""

        check = next(
            (
                candidate
                for candidate in compliance.get("checks", [])
                if candidate.get("code") == code
            ),
            None,
        )
        if check is None:
            raise AssertionError(
                f"Compliance response did not include {code!r}: {compliance!r}"
            )
        return check

    @staticmethod
    def _required(value: str | None, label: str) -> str:
        """Return a required state value with a concise assertion on absence."""

        if not value:
            raise AssertionError(f"{label} was unavailable.")
        return value

    @staticmethod
    def _selector_text(locator: tuple[str, str]) -> str:
        """Render one Selenium locator for artifact readability."""

        return f"{locator[0]}={locator[1]}"

    @staticmethod
    def _project_root() -> Path:
        """Return the repository root from this durable browser artifact."""

        return Path(__file__).resolve().parents[2]

    def _log_stage(self, outcome: str, stage: str) -> None:
        """Emit a compact, CI-readable stage line."""

        self.logger.info("%s %s %s", STAGE_PREFIX, outcome, stage)

    def _write_text(self, file_name: str, content: str) -> None:
        """Write diagnostics with deterministic UTF-8 handling."""

        (self.state.artifact_directory / file_name).write_text(
            content,
            encoding="utf-8",
            errors="replace",
        )

    def _write_json(self, file_name: str, payload: Any) -> None:
        """Write formatted JSON diagnostics without binary or opaque-token output."""

        self._write_text(
            file_name,
            json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        )


# PUBLIC_INTERFACE
def parse_arguments() -> argparse.Namespace:
    """Parse non-interactive execution options for the focused validation artifact."""

    parser = argparse.ArgumentParser(
        description="Run durable Batch 6 expiry and re-validation browser validation."
    )
    parser.add_argument(
        "--headed",
        action="store_true",
        help="Show Chrome instead of the default headless execution mode.",
    )
    parser.add_argument(
        "--web-base-url",
        default=DEFAULT_WEB_BASE_URL,
        help="Rendered web application base URL.",
    )
    parser.add_argument(
        "--api-base-url",
        default=DEFAULT_API_BASE_URL,
        help="API base URL for browser-session assertions and reset health checks.",
    )
    parser.add_argument(
        "--artifacts-dir",
        default=Path("artifacts") / "batch6",
        type=Path,
        help="Directory in which durable diagnostic artifacts are stored.",
    )
    return parser.parse_args()


# PUBLIC_INTERFACE
def main() -> int:
    """Run the focused validation and return a CI-friendly exit status."""

    arguments = parse_arguments()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    validation = Batch6BrowserValidation(
        artifact_root=arguments.artifacts_dir,
        web_base_url=arguments.web_base_url,
        api_base_url=arguments.api_base_url,
        headless=not arguments.headed,
    )
    try:
        validation.run()
    except (AssertionError, TimeoutException, WebDriverException, RuntimeError):
        logging.exception(
            "%s FAIL validation; diagnostics saved under %s",
            STAGE_PREFIX,
            validation.state.artifact_directory,
        )
        return 1
    except BaseException:
        logging.exception(
            "%s FAIL unexpected validation error; diagnostics saved under %s",
            STAGE_PREFIX,
            validation.state.artifact_directory,
        )
        return 1

    logging.info(
        "%s PASS validation; diagnostics saved under %s",
        STAGE_PREFIX,
        validation.state.artifact_directory,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
