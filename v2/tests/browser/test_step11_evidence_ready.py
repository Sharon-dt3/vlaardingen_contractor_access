#!/usr/bin/env python3
"""Durable browser validation for the STEP-11 evidence-ready workflow.

Run from the repository root after the local Compose application is healthy:

    python tests/browser/test_step11_evidence_ready.py

The script drives the rendered `/login` form as `sheq.demo`, executes the
invitation-to-evidence-ready path, proves the visible UI state and authenticated
API/audit state, and always restores the deterministic seed baseline.
Configuration may be overridden with STEP11_* environment variables; defaults
match the repository's local Compose demonstration profile.
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
from uuid import uuid4

try:
    from selenium import webdriver
    from selenium.common.exceptions import TimeoutException, WebDriverException
    from selenium.webdriver import ChromeOptions
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.common.by import By
    from selenium.webdriver.remote.webdriver import WebDriver
    from selenium.webdriver.support import expected_conditions as expected
    from selenium.webdriver.support.ui import Select, WebDriverWait
except ImportError as error:  # pragma: no cover - runner-environment guard
    raise SystemExit(
        "STEP-11 requires Selenium. Install the approved browser-test dependency "
        "in the execution environment before running this script."
    ) from error


STAGE_PREFIX = "[STEP-11]"
EXPECTED_CHROME_MAJOR = os.environ.get("STEP11_CHROME_MAJOR", "153")
DEFAULT_WEB_BASE_URL = os.environ.get("STEP11_WEB_BASE_URL", "http://localhost:3000")
DEFAULT_API_BASE_URL = os.environ.get("STEP11_API_BASE_URL", "http://localhost:8000")
DEMO_HANDLE = os.environ.get("STEP11_DEMO_HANDLE", "sheq.demo")
DEMO_PASSWORD = os.environ.get("STEP11_DEMO_PASSWORD", "renewi-demo-access")
SHORT_WAIT_SECONDS = int(os.environ.get("STEP11_SHORT_WAIT_SECONDS", "20"))
LONG_WAIT_SECONDS = int(os.environ.get("STEP11_LONG_WAIT_SECONDS", "60"))
T = TypeVar("T")


@dataclass
class WorkflowState:
    """Mutable identifiers and diagnostics context for one isolated run."""

    artifact_directory: Path
    web_base_url: str
    api_base_url: str
    driver: WebDriver | None = None
    invitation_id: str | None = None
    person_id: str | None = None
    evidence_id: str | None = None
    invitee_email: str = field(
        default_factory=lambda: (
            f"step11-{uuid4().hex[:12]}@demo.example.com"
        )
    )
    company_name: str = "STEP-11 Fictional Services B.V."
    purpose: str = "STEP-11 deterministic browser validation"
    stage_number: int = 0
    last_selector: str | None = None


class Step11BrowserValidation:
    """Runs and documents one complete, reproducible STEP-11 browser journey."""

    def __init__(
        self,
        *,
        artifact_root: Path,
        web_base_url: str,
        api_base_url: str,
        headless: bool,
    ) -> None:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        self.state = WorkflowState(
            artifact_directory=artifact_root / f"run-{timestamp}-{uuid4().hex[:8]}",
            web_base_url=web_base_url.rstrip("/"),
            api_base_url=api_base_url.rstrip("/"),
        )
        self.state.artifact_directory.mkdir(parents=True, exist_ok=True)
        self.headless = headless
        self.logger = logging.getLogger("step11")
        self._write_json(
            "run_configuration.json",
            {
                "web_base_url": self.state.web_base_url,
                "api_base_url": self.state.api_base_url,
                "expected_chrome_major": EXPECTED_CHROME_MAJOR,
                "headless": headless,
                "invitee_email": self.state.invitee_email,
            },
        )

    def run(self) -> None:
        """Execute all browser stages and always restore the deterministic baseline."""
        workflow_error: BaseException | None = None
        cleanup_error: BaseException | None = None

        try:
            self.state.driver = self._create_driver()
            self._record_browser_versions()
            self._run_stage("login", self.login)
            self._run_stage("create_invitation", self.create_invitation)
            self._run_stage("complete_registration", self.complete_registration)
            self._run_stage("upload_evidence", self.upload_evidence)
            self._run_stage("verify_evidence_state", self.verify_evidence_state)
            self._run_stage("verify_api_state", self.verify_api_state)
            self._run_stage("verify_audit_history", self.verify_audit_history)
        except BaseException as error:
            workflow_error = error
        finally:
            try:
                self.reset_baseline()
            except BaseException as error:
                cleanup_error = error
            finally:
                if self.state.driver is not None:
                    self.state.driver.quit()

        if workflow_error is not None:
            if cleanup_error is not None:
                raise RuntimeError(
                    "The workflow failed and deterministic cleanup also failed. "
                    "Inspect the staged artifacts before any further run."
                ) from workflow_error
            raise workflow_error

        if cleanup_error is not None:
            raise cleanup_error

    def login(self) -> None:
        """Authenticate through the actual rendered local-demo login form."""
        driver = self._driver
        driver.get(f"{self.state.web_base_url}/login")

        handle = self._visible((By.ID, "handle"))
        password = self._visible((By.ID, "password"))
        handle.clear()
        handle.send_keys(DEMO_HANDLE)
        password.clear()
        password.send_keys(DEMO_PASSWORD)

        self._click(
            (By.XPATH, "//form//button[@type='submit' and normalize-space()='Sign in']"),
            "rendered login submit button",
        )
        self._wait().until(
            lambda current_driver: "/login" not in current_driver.current_url
        )
        self._wait().until(
            expected.presence_of_element_located(
                (By.XPATH, "//*[contains(normalize-space(), 'Renewi Access')]")
            )
        )

    def create_invitation(self) -> None:
        """Create a unique invitation through the rendered invitation workspace."""
        driver = self._driver
        driver.get(f"{self.state.web_base_url}/invitations")
        create_panel = (
            By.XPATH,
            "//section[@aria-labelledby='create-invitation']",
        )
        self._visible(create_panel)

        site_select = self._visible(
            (
                By.CSS_SELECTOR,
                "section[aria-labelledby='create-invitation'] select[name='site_id']",
            )
        )
        site_options = [
            {"value": option.get_attribute("value"), "text": option.text}
            for option in Select(site_select).options
            if option.get_attribute("value")
        ]
        self._write_json("invitation_site_options.json", site_options)
        if not site_options:
            raise AssertionError("The rendered invitation form exposed no active site.")
        Select(site_select).select_by_value(str(site_options[0]["value"]))

        population_select = self._visible(
            (
                By.CSS_SELECTOR,
                "section[aria-labelledby='create-invitation'] select[name='population']",
            )
        )
        Select(population_select).select_by_value("maintenance_contractor")

        self._replace_input(
            (
                By.CSS_SELECTOR,
                "section[aria-labelledby='create-invitation'] input[name='invitee_email']",
            ),
            self.state.invitee_email,
        )
        self._replace_input(
            (
                By.CSS_SELECTOR,
                "section[aria-labelledby='create-invitation'] input[name='company_name']",
            ),
            self.state.company_name,
        )
        self._replace_input(
            (
                By.CSS_SELECTOR,
                "section[aria-labelledby='create-invitation'] input[name='purpose']",
            ),
            self.state.purpose,
        )
        self._click(
            (
                By.XPATH,
                "//section[@aria-labelledby='create-invitation']"
                "//button[@type='submit' and contains(normalize-space(), 'Create invitation')]",
            ),
            "create invitation submit button",
        )

        invitation = self._wait_for_invitation()
        if (
            invitation.get("invitee_email") != self.state.invitee_email
            or invitation.get("company_name") != self.state.company_name
            or invitation.get("purpose") != self.state.purpose
        ):
            raise AssertionError(
                "The invitation API did not retain the submitted invitation details."
            )
        self.state.invitation_id = str(invitation["id"])
        self._write_json("created_invitation.json", invitation)
        self._wait().until(
            expected.visibility_of_element_located(
                (By.ID, "complete-registration")
            )
        )
        self._wait().until(
            expected.visibility_of_element_located(
                (
                    By.XPATH,
                    "//section[@aria-labelledby='visible-invitations']"
                    f"//span[normalize-space()='{self.state.invitee_email}']",
                )
            )
        )

    def complete_registration(self) -> None:
        """Complete the rendered create-or-match registration form."""
        self._visible((By.ID, "complete-registration"))
        self._replace_input(
            (
                By.CSS_SELECTOR,
                "section[aria-labelledby='complete-registration'] input[name='first_name']",
            ),
            "Step",
        )
        self._replace_input(
            (
                By.CSS_SELECTOR,
                "section[aria-labelledby='complete-registration'] input[name='last_name']",
            ),
            "Eleven",
        )
        self._replace_input(
            (
                By.CSS_SELECTOR,
                "section[aria-labelledby='complete-registration'] input[name='email']",
            ),
            self.state.invitee_email,
        )
        self._click(
            (
                By.XPATH,
                "//section[@aria-labelledby='complete-registration']"
                "//button[@type='submit' and contains(normalize-space(), 'Complete registration')]",
            ),
            "complete registration submit button",
        )
        self._visible((By.ID, "evidence-workspace"))

        invitation = self._wait_for_invitation(require_person=True)
        self.state.person_id = str(invitation["person_id"])
        self._write_json("registered_invitation.json", invitation)

    def upload_evidence(self) -> None:
        """Upload one visible synthetic document through the unified evidence flow."""
        workspace_locator = "//section[@aria-labelledby='evidence-workspace']"
        evidence_type = self._visible(
            (
                By.XPATH,
                f"{workspace_locator}//label[normalize-space()='Evidence type']/select",
            )
        )
        Select(evidence_type).select_by_value("driving_licence")

        document_path = self.state.artifact_directory / "synthetic-driving-licence.pdf"
        document_path.write_bytes(
            b"%PDF-1.4\nDEMO NOT A REAL CREDENTIAL\nSTEP-11 synthetic driving licence\n"
        )
        file_input = self._visible((By.XPATH, f"{workspace_locator}//input[@type='file']"))
        file_input.send_keys(str(document_path))
        self._click(
            (
                By.XPATH,
                f"{workspace_locator}//button[normalize-space()='Upload and extract']",
            ),
            "upload and extract evidence button",
        )

        verify_locator = (By.XPATH, "//button[normalize-space()='Verify evidence']")
        self._wait(LONG_WAIT_SECONDS).until(
            lambda current_driver: (
                element := current_driver.find_element(*verify_locator)
            ).is_displayed()
            and element.is_enabled()
        )
        evidence = self._wait_for_attached_evidence()
        if evidence.get("status") != "extracted" or not evidence.get("extracted_fields"):
            raise AssertionError(
                "The unified upload did not return backend extraction results: "
                f"{evidence!r}"
            )
        self.state.evidence_id = str(evidence["id"])
        self._write_json("uploaded_evidence.json", evidence)

    def verify_evidence_state(self) -> None:
        """Verify the already-extracted evidence and assert the Evidence ready state."""
        verify_locator = (By.XPATH, "//button[normalize-space()='Verify evidence']")
        self._click(verify_locator, "verify evidence button")

        evidence_ready_locator = (
            By.XPATH,
            "//*[normalize-space()='Evidence Ready']",
        )
        evidence_ready = self._wait(LONG_WAIT_SECONDS).until(
            expected.visibility_of_element_located(evidence_ready_locator)
        )
        self._capture_diagnostics(
            "evidence_ready",
            selector=self._selector_text(evidence_ready_locator),
            element=evidence_ready,
        )

    def verify_api_state(self) -> None:
        """Assert the actual invitation endpoint reports the evidence-ready state."""
        if self.state.invitation_id is None:
            raise AssertionError("Invitation ID was unavailable for the API assertion.")

        invitation = self._browser_api_json(
            f"/api/invitations/{self.state.invitation_id}"
        )
        self._write_json("api_invitation.json", invitation)

        # The current API contract exposes the evidence-ready decision as the
        # invitation status enum rather than a separate boolean property.
        if invitation.get("status") != "evidence_ready":
            raise AssertionError(
                "The invitation API did not report status='evidence_ready': "
                f"{invitation.get('status')!r}"
            )
        if str(invitation.get("id")) != self.state.invitation_id:
            raise AssertionError("The API returned a different invitation record.")
        if (
            invitation.get("invitee_email") != self.state.invitee_email
            or invitation.get("company_name") != self.state.company_name
            or invitation.get("purpose") != self.state.purpose
        ):
            raise AssertionError(
                "The invitation API did not retain the submitted invitation details."
            )

    def verify_audit_history(self) -> None:
        """Assert all required audit actions occur in chronological order."""
        if self.state.invitation_id is None or self.state.evidence_id is None:
            raise AssertionError("Invitation/evidence identifiers were unavailable for audit.")

        audit_events = self._browser_api_json("/api/audit/events")
        self._write_json("audit.json", audit_events)
        expected_actions = [
            "invitation.created",
            "registration.completed",
            "evidence.uploaded",
            "evidence.extracted",
            "evidence.verified",
            "invitation.evidence_ready",
        ]

        related_ids = {self.state.invitation_id, self.state.evidence_id}
        related_events = [
            event
            for event in audit_events
            if str(event.get("entity_id")) in related_ids
            or event.get("details", {}).get("person_id") == self.state.person_id
        ]
        self._write_json("related_audit_events.json", related_events)
        related_actions = [str(event.get("action")) for event in related_events]

        positions: list[int] = []
        for action in expected_actions:
            try:
                positions.append(related_actions.index(action))
            except ValueError as error:
                raise AssertionError(
                    f"Required audit event {action!r} was absent. "
                    f"Observed related actions: {related_actions!r}"
                ) from error

        if positions != sorted(positions) or len(set(positions)) != len(positions):
            raise AssertionError(
                "Required audit events were not in strict chronological order: "
                f"{list(zip(expected_actions, positions))!r}"
            )

        timestamps = [related_events[position].get("occurred_at") for position in positions]
        if timestamps != sorted(timestamps):
            raise AssertionError(
                "Audit endpoint did not return the required actions chronologically: "
                f"{timestamps!r}"
            )

    def reset_baseline(self) -> None:
        """Reset, seed, and health-check the local deterministic Compose baseline."""
        stage = "reset_baseline"
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
            self._write_json("baseline_health.json", health)
            self._assert_local_demo_health(health)
        except BaseException:
            self._log_stage("FAIL", stage)
            self._write_text(
                "baseline_cleanup_error.txt",
                traceback.format_exc(),
            )
            raise
        else:
            self._log_stage("PASS", stage)

    @property
    def _driver(self) -> WebDriver:
        if self.state.driver is None:
            raise RuntimeError("The Chrome driver was not initialized.")
        return self.state.driver

    def _create_driver(self) -> WebDriver:
        options = ChromeOptions()
        if self.headless:
            options.add_argument("--headless=new")
        options.add_argument("--window-size=1440,900")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--no-sandbox")

        chrome_binary = os.environ.get("STEP11_CHROME_BINARY")
        if chrome_binary:
            options.binary_location = chrome_binary

        driver_path = os.environ.get("STEP11_CHROMEDRIVER_PATH")
        service = Service(executable_path=driver_path) if driver_path else Service()
        driver = webdriver.Chrome(service=service, options=options)
        driver.set_page_load_timeout(LONG_WAIT_SECONDS)
        return driver

    def _record_browser_versions(self) -> None:
        capabilities = self._driver.capabilities
        chrome = capabilities.get("chrome", {})
        browser_version = str(capabilities.get("browserVersion", ""))
        driver_version = str(chrome.get("chromedriverVersion", ""))
        self._write_json(
            "browser_versions.json",
            {
                "browser_version": browser_version,
                "chromedriver_version": driver_version,
                "expected_major": EXPECTED_CHROME_MAJOR,
            },
        )

        browser_major = browser_version.split(".", 1)[0]
        driver_major = driver_version.split(".", 1)[0]
        if browser_major != EXPECTED_CHROME_MAJOR or driver_major != EXPECTED_CHROME_MAJOR:
            raise AssertionError(
                "STEP-11 requires the compatible Chrome/ChromeDriver "
                f"{EXPECTED_CHROME_MAJOR} pair; found Chrome={browser_version!r}, "
                f"ChromeDriver={driver_version!r}."
            )

    def _run_stage(self, stage: str, action: Callable[[], T]) -> T:
        self.state.stage_number += 1
        self._log_stage("START", stage)
        try:
            result = action()
        except BaseException:
            self._log_stage("FAIL", stage)
            self._capture_diagnostics(
                f"{self.state.stage_number:02d}_{stage}_failure",
                selector=self.state.last_selector,
            )
            raise
        self._capture_diagnostics(
            f"{self.state.stage_number:02d}_{stage}",
            selector=self.state.last_selector,
        )
        self._log_stage("PASS", stage)
        return result

    def _wait(self, seconds: int = SHORT_WAIT_SECONDS) -> WebDriverWait:
        return WebDriverWait(self._driver, seconds)

    def _visible(self, locator: tuple[str, str]) -> Any:
        self.state.last_selector = self._selector_text(locator)
        return self._wait().until(expected.visibility_of_element_located(locator))

    def _click(self, locator: tuple[str, str], description: str) -> None:
        self.state.last_selector = self._selector_text(locator)
        element = self._wait().until(expected.element_to_be_clickable(locator))
        element.click()
        self.logger.info("%s Clicked %s using %s", STAGE_PREFIX, description, self.state.last_selector)

    def _replace_input(self, locator: tuple[str, str], value: str) -> None:
        element = self._visible(locator)
        element.clear()
        element.send_keys(value)

    def _wait_for_invitation(self, *, require_person: bool = False) -> dict[str, Any]:
        def find_invitation(_: WebDriver) -> dict[str, Any] | bool:
            invitations = self._browser_api_json("/api/invitations")
            invitation = next(
                (
                    item
                    for item in invitations
                    if item.get("invitee_email") == self.state.invitee_email
                ),
                None,
            )
            if invitation is None:
                return False
            if require_person and not invitation.get("person_id"):
                return False
            return invitation

        return self._wait(LONG_WAIT_SECONDS).until(find_invitation)

    def _wait_for_attached_evidence(self) -> dict[str, Any]:
        if self.state.person_id is None or self.state.invitation_id is None:
            raise AssertionError("Person/invitation ID unavailable for evidence lookup.")

        def find_evidence(_: WebDriver) -> dict[str, Any] | bool:
            evidence_records = self._browser_api_json(
                f"/api/people/{self.state.person_id}/evidence"
            )
            return next(
                (
                    record
                    for record in evidence_records
                    if str(record.get("invitation_id")) == self.state.invitation_id
                ),
                False,
            )

        return self._wait(LONG_WAIT_SECONDS).until(find_evidence)

    def _browser_api_json(self, path: str) -> Any:
        """Fetch one API path in the rendered browser's authenticated session."""
        if not path.startswith("/"):
            raise ValueError("Browser API paths must start with '/'.")
        script = """
            const done = arguments[arguments.length - 1];
            fetch(arguments[0], {
                credentials: "include",
                headers: { Accept: "application/json" }
            }).then(async (response) => {
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
        )
        if not response["ok"]:
            raise AssertionError(
                f"Authenticated API request {path} failed with HTTP "
                f"{response['status']}: {response['payload']!r}"
            )
        return response["payload"]

    def _capture_diagnostics(
        self,
        label: str,
        *,
        selector: str | None,
        element: Any | None = None,
    ) -> None:
        """Persist UTF-8-safe browser diagnostics without masking original failures."""
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

            inspection: dict[str, Any] = {
                "selector": selector,
                "element_exists": False,
                "element_visible": False,
                "element_enabled": False,
                "invitation_id": self.state.invitation_id,
                "person_id": self.state.person_id,
                "evidence_id": self.state.evidence_id,
            }
            candidate = element
            if candidate is None and selector:
                candidate = self._find_from_selector_text(selector)
            if candidate is not None:
                inspection.update(
                    {
                        "element_exists": True,
                        "element_visible": candidate.is_displayed(),
                        "element_enabled": candidate.is_enabled(),
                        "tag": candidate.tag_name,
                        "outer_html": candidate.get_attribute("outerHTML"),
                    }
                )
            self._write_json(f"{prefix}_dom.json", inspection)
        except WebDriverException as diagnostic_error:
            self._write_text(
                f"{prefix}_diagnostic_capture_error.txt",
                f"{type(diagnostic_error).__name__}: {diagnostic_error}",
            )

    def _find_from_selector_text(self, selector: str) -> Any | None:
        try:
            by, value = selector.split("=", 1)
            return self._driver.find_element(by, value)
        except (ValueError, WebDriverException):
            return None

    def _run_compose_command(self, arguments: list[str], output_path: Path) -> None:
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
                f"Cleanup command failed ({result.returncode}): "
                f"docker compose {' '.join(arguments)}"
            )

    def _wait_for_healthy_api(self) -> dict[str, Any]:
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
            except (urllib.error.URLError, TimeoutError, AssertionError, json.JSONDecodeError) as error:
                last_error = error
                time.sleep(2)
        raise AssertionError("The API did not return healthy after reset/reseed.") from last_error

    @staticmethod
    def _assert_local_demo_health(health: dict[str, Any]) -> None:
        if health.get("status") != "ready":
            raise AssertionError(f"Health status was not ready: {health!r}")
        if health.get("demo_mode") is not True:
            raise AssertionError(f"Health did not confirm DEMO mode: {health!r}")
        providers = health.get("providers")
        if not isinstance(providers, dict) or not providers:
            raise AssertionError(f"Health did not expose provider modes: {health!r}")

        permitted_modes = {"demo", "local", "mock"}
        provider_modes = {str(value).lower() for value in providers.values()}
        if not provider_modes.issubset(permitted_modes):
            raise AssertionError(
                "Health exposed an unexpected non-DEMO/LOCAL provider mode: "
                f"{providers!r}"
            )

    @staticmethod
    def _project_root() -> Path:
        return Path(__file__).resolve().parents[2]

    @staticmethod
    def _selector_text(locator: tuple[str, str]) -> str:
        return f"{locator[0]}={locator[1]}"

    def _log_stage(self, outcome: str, stage: str) -> None:
        self.logger.info("%s %s %s", STAGE_PREFIX, outcome, stage)

    def _write_text(self, file_name: str, content: str) -> None:
        (self.state.artifact_directory / file_name).write_text(
            content,
            encoding="utf-8",
            errors="replace",
        )

    def _write_json(self, file_name: str, payload: Any) -> None:
        self._write_text(
            file_name,
            json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        )


def parse_arguments() -> argparse.Namespace:
    """Parse non-interactive execution options for one browser-validation run."""
    parser = argparse.ArgumentParser(
        description="Run the durable STEP-11 evidence-ready browser validation."
    )
    parser.add_argument(
        "--headed",
        action="store_true",
        help="Show Chrome instead of using the default non-interactive headless mode.",
    )
    parser.add_argument(
        "--web-base-url",
        default=DEFAULT_WEB_BASE_URL,
        help="Rendered web application base URL.",
    )
    parser.add_argument(
        "--api-base-url",
        default=DEFAULT_API_BASE_URL,
        help="API base URL used for authenticated browser checks and health cleanup.",
    )
    parser.add_argument(
        "--artifacts-dir",
        type=Path,
        default=Path("artifacts") / "step11",
        help="Directory in which this run's diagnostics are stored.",
    )
    return parser.parse_args()


def main() -> int:
    """Run one non-interactive STEP-11 validation cycle and report artifact location."""
    arguments = parse_arguments()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    validation = Step11BrowserValidation(
        artifact_root=arguments.artifacts_dir,
        web_base_url=arguments.web_base_url,
        api_base_url=arguments.api_base_url,
        headless=not arguments.headed,
    )
    try:
        validation.run()
    except BaseException:
        logging.exception(
            "%s FAIL workflow; diagnostics saved under %s",
            STAGE_PREFIX,
            validation.state.artifact_directory,
        )
        return 1

    logging.info(
        "%s PASS workflow; artifacts saved under %s",
        STAGE_PREFIX,
        validation.state.artifact_directory,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
