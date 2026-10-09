#!/usr/bin/env python3
"""Durable browser validation for the STEP-14 training-to-QR workflow.

Run from the repository root after the local Compose application is healthy:

    python tests/browser/test_step14_training_to_qr.py --runs 2

The script uses the rendered application as the seeded ``sheq.demo`` compliance
manager. For each clean deterministic baseline it selects Alex van Dijk, passes
both required modules through the visible UI, proves visible eligible compliance
and granted approval, issues a token through the UI, and captures the rendered
one-time QR card. Authenticated browser-session API checks and chronological
audit evidence supplement, but do not replace, the rendered assertions.

Every run performs reset/seed/health verification before the workflow and again
from ``finally`` cleanup. Diagnostics are written as UTF-8 under
``artifacts/step14/run-*/`` without printing opaque QR payloads to the log.
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
    from selenium.webdriver.support.ui import Select, WebDriverWait
except ImportError as error:  # pragma: no cover - execution environment guard
    raise SystemExit(
        "STEP-14 requires Selenium. Install the approved browser-test dependency "
        "in the execution environment before running this script."
    ) from error


STAGE_PREFIX = "[STEP-14]"
EXPECTED_CHROME_MAJOR = os.environ.get("STEP14_CHROME_MAJOR", "153")
DEFAULT_WEB_BASE_URL = os.environ.get("STEP14_WEB_BASE_URL", "http://localhost:3000")
DEFAULT_API_BASE_URL = os.environ.get("STEP14_API_BASE_URL", "http://localhost:8000")
DEMO_HANDLE = os.environ.get("STEP14_DEMO_HANDLE", "sheq.demo")
DEMO_PASSWORD = os.environ.get("STEP14_DEMO_PASSWORD", "renewi-demo-access")
SHORT_WAIT_SECONDS = int(os.environ.get("STEP14_SHORT_WAIT_SECONDS", "20"))
LONG_WAIT_SECONDS = int(os.environ.get("STEP14_LONG_WAIT_SECONDS", "60"))
T = TypeVar("T")

# These choices correspond to the deterministic synthetic seed fixture. The
# public module API intentionally does not expose answer keys, so the test uses
# the fixture's known answers only to exercise the same rendered controls a
# manager uses. It never logs these answers or any issued QR payload.
REQUIRED_MODULES: tuple[tuple[str, tuple[tuple[str, str], ...]], ...] = (
    (
        "sheq_basics",
        (
            ("ppe", "Wear the required personal protective equipment"),
            ("incident", "Report it through the site safety process"),
        ),
    ),
    (
        "vlaardingen_site_rules",
        (
            ("gate", "Present the assigned opaque access token"),
            ("escort", "Follow site signage and host instructions"),
        ),
    ),
)


@dataclass
class WorkflowState:
    """Mutable identifiers and diagnostics context for one isolated run."""

    artifact_directory: Path
    web_base_url: str
    api_base_url: str
    cycle_number: int
    driver: WebDriver | None = None
    person_id: str | None = None
    visit_id: str | None = None
    token_id: str | None = None
    stage_number: int = 0
    last_selector: str | None = None
    completed_module_ids: dict[str, str] = field(default_factory=dict)


class Step14BrowserValidation:
    """Run one clean, reproducible manager-visible Batch 3 browser journey."""

    def __init__(
        self,
        *,
        artifact_root: Path,
        web_base_url: str,
        api_base_url: str,
        headless: bool,
        cycle_number: int,
    ) -> None:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        self.state = WorkflowState(
            artifact_directory=artifact_root
            / f"run-{cycle_number}-{timestamp}-{os.urandom(4).hex()}",
            web_base_url=web_base_url.rstrip("/"),
            api_base_url=api_base_url.rstrip("/"),
            cycle_number=cycle_number,
        )
        self.state.artifact_directory.mkdir(parents=True, exist_ok=True)
        self.headless = headless
        self.logger = logging.getLogger(f"step14.run{cycle_number}")
        self._write_json(
            "run_configuration.json",
            {
                "cycle_number": cycle_number,
                "web_base_url": self.state.web_base_url,
                "api_base_url": self.state.api_base_url,
                "expected_chrome_major": EXPECTED_CHROME_MAJOR,
                "headless": headless,
                "required_module_codes": [module[0] for module in REQUIRED_MODULES],
            },
        )

    def run(self) -> None:
        """Execute the workflow and restore a deterministic baseline in all cases."""
        workflow_error: BaseException | None = None
        cleanup_error: BaseException | None = None

        try:
            self.reset_baseline("prepare_baseline")
            self.state.driver = self._create_driver()
            self._record_browser_versions()
            self._run_stage("login", self.login)
            self._run_stage("select-alex", self.select_alex)
            self._run_stage(
                "training-module-1",
                lambda: self.complete_training_module(REQUIRED_MODULES[0]),
            )
            self._run_stage(
                "training-module-2",
                lambda: self.complete_training_module(REQUIRED_MODULES[1]),
            )
            self._run_stage("compliance", self.verify_compliance)
            self._run_stage("approval", self.create_and_grant_approval)
            self._run_stage("token-issuance", self.issue_token)
            self._run_stage("qr-rendering", self.verify_qr_rendering)
            self._run_stage("api-and-audit-evidence", self.verify_api_and_audit_evidence)
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
                    "The rendered workflow and its deterministic cleanup both "
                    "failed. Inspect artifacts before attempting another run."
                ) from workflow_error
            raise workflow_error

        if cleanup_error is not None:
            raise cleanup_error

    def login(self) -> None:
        """Authenticate through the real rendered local-demo login form."""
        driver = self._driver
        driver.get(f"{self.state.web_base_url}/login")

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
        self._wait().until(
            expected.presence_of_element_located(
                (By.XPATH, "//*[contains(normalize-space(), 'Renewi Access')]")
            )
        )

    def select_alex(self) -> None:
        """Select Alex's deterministic happy-path visit by stable option value."""
        self._driver.get(f"{self.state.web_base_url}/visits")
        visit_select = self._visible((By.ID, "batch3-visit-selection"))

        people = self._browser_api_json("/api/people")
        alex = next(
            (
                person
                for person in people
                if person.get("first_name") == "Alex"
                and person.get("last_name") == "van Dijk"
            ),
            None,
        )
        if alex is None:
            raise AssertionError("The deterministic Alex van Dijk person was absent.")

        visits = self._browser_api_json("/api/visits")
        alex_visit = next(
            (
                visit
                for visit in visits
                if str(visit.get("person_id")) == str(alex.get("id"))
                and visit.get("status") == "active"
            ),
            None,
        )
        if alex_visit is None:
            raise AssertionError("No active deterministic visit was available for Alex.")

        self.state.person_id = str(alex["id"])
        self.state.visit_id = str(alex_visit["id"])
        self._write_json(
            "selected_alex.json",
            {
                "person_id": self.state.person_id,
                "visit_id": self.state.visit_id,
                "visit_purpose": alex_visit.get("purpose"),
                "visit_status": alex_visit.get("status"),
            },
        )

        Select(visit_select).select_by_value(self.state.visit_id)
        self._wait().until(
            expected.visibility_of_element_located(
                (
                    By.XPATH,
                    "//section[@aria-labelledby='selected-visit-summary']"
                    "//h2[normalize-space()='Alex van Dijk']",
                )
            )
        )
        self._visible(
            (
                By.XPATH,
                "//section[@aria-labelledby='training-workspace']"
                "//select[ancestor::section[@aria-labelledby='training-workspace']]",
            )
        )

    def complete_training_module(
        self,
        module_spec: tuple[str, tuple[tuple[str, str], ...]],
    ) -> None:
        """Submit one seeded module through its visible radio controls."""
        code, answers = module_spec
        modules = self._browser_api_json("/api/training/modules")
        module = next((candidate for candidate in modules if candidate.get("code") == code), None)
        if module is None:
            raise AssertionError(f"Required training module {code!r} was absent.")

        module_id = str(module["id"])
        self.state.completed_module_ids[code] = module_id
        module_select_locator = (
            By.XPATH,
            "//section[@aria-labelledby='training-workspace']"
            "//select[ancestor::section[@aria-labelledby='training-workspace']]",
        )
        module_select = self._visible(module_select_locator)
        Select(module_select).select_by_value(module_id)

        training_section = "//section[@aria-labelledby='training-workspace']"
        for question_id, answer_text in answers:
            answer_locator = (
                By.XPATH,
                f"{training_section}//label[.//input[@name={self._xpath_literal(question_id)}]"
                f" and .//span[normalize-space()={self._xpath_literal(answer_text)}]]"
                "//input",
            )
            self._click(answer_locator, f"{code} answer for {question_id}")

        submit_locator = (
            By.XPATH,
            f"{training_section}//button[@type='submit' and not(@disabled)]",
        )
        self._click(submit_locator, f"{code} rendered scored-attempt submit button")

        expected_passed_cards = len(self.state.completed_module_ids)
        passed_card_locator = (
            By.XPATH,
            f"{training_section}//article[.//*[normalize-space()='Passed']]",
        )
        self._wait(LONG_WAIT_SECONDS).until(
            lambda current_driver: len(
                current_driver.find_elements(*passed_card_locator)
            )
            >= expected_passed_cards
        )

        if self.state.person_id is None:
            raise AssertionError("Alex's identifier was unavailable after visit selection.")

        results = self._wait(LONG_WAIT_SECONDS).until(
            lambda _: self._matching_passed_result(module_id)
        )
        self._write_json(f"training_{code}_results.json", results)

    def verify_compliance(self) -> None:
        """Prove the visible API-calculated compliance evaluation is eligible."""
        compliance_section = "//section[@aria-labelledby='compliance-workspace']"
        eligible_locator = (
            By.XPATH,
            f"{compliance_section}//*[normalize-space()='Eligible']",
        )
        eligible = self._wait(LONG_WAIT_SECONDS).until(
            expected.visibility_of_element_located(eligible_locator)
        )
        self._capture_diagnostics(
            "compliance_eligible",
            selector=self._selector_text(eligible_locator),
            element=eligible,
        )

    def create_and_grant_approval(self) -> None:
        """Create a current approval snapshot and grant it through the UI."""
        compliance_section = "//section[@aria-labelledby='compliance-workspace']"
        self._click(
            (
                By.XPATH,
                f"{compliance_section}"
                "//button[normalize-space()='Create approval evaluation']",
            ),
            "create approval evaluation button",
        )
        self._wait(LONG_WAIT_SECONDS).until(
            expected.visibility_of_element_located(
                (
                    By.XPATH,
                    f"{compliance_section}"
                    "//*[normalize-space()='Approval snapshot created']",
                )
            )
        )
        self._click(
            (
                By.XPATH,
                f"{compliance_section}"
                "//button[normalize-space()='Approve eligible snapshot']",
            ),
            "approve eligible snapshot button",
        )
        granted_locator = (
            By.XPATH,
            f"{compliance_section}//*[normalize-space()='Approved']",
        )
        granted = self._wait(LONG_WAIT_SECONDS).until(
            expected.visibility_of_element_located(granted_locator)
        )
        self._capture_diagnostics(
            "approval_granted",
            selector=self._selector_text(granted_locator),
            element=granted,
        )

    def issue_token(self) -> None:
        """Issue an eligible visit token through the visible token workspace."""
        token_section = "//section[@aria-labelledby='access-token-management']"
        self._click(
            (
                By.XPATH,
                f"{token_section}"
                "//button[normalize-space()='Issue eligible visit token']",
            ),
            "issue eligible visit token button",
        )
        self._wait(LONG_WAIT_SECONDS).until(
            expected.visibility_of_element_located(
                (
                    By.XPATH,
                    "//*[normalize-space()='One-time QR payload']",
                )
            )
        )

        if self.state.visit_id is None:
            raise AssertionError("Selected visit identifier was unavailable for token check.")

        tokens = self._wait(LONG_WAIT_SECONDS).until(
            lambda _: self._active_visit_tokens()
        )
        self.state.token_id = str(tokens[-1]["id"])
        self._write_json(
            "issued_token_metadata.json",
            {
                "token_id": self.state.token_id,
                "visit_id": self.state.visit_id,
                "status": tokens[-1].get("status"),
                "expires_at": tokens[-1].get("expires_at"),
            },
        )

    def verify_qr_rendering(self) -> None:
        """Assert the visible QR card exists without reading its opaque payload."""
        payload_label_locator = (By.XPATH, "//*[normalize-space()='One-time QR payload']")
        payload_label = self._visible(payload_label_locator)
        qr_card_locator = (
            By.XPATH,
            "//div[starts-with(@id, 'qr-token-') and "
            ".//*[normalize-space()='One-time QR payload']]",
        )
        qr_card = self._visible(qr_card_locator)
        qr_svg_locator = (
            By.CSS_SELECTOR,
            "div[id^='qr-token-'] svg[role='img']",
        )
        qr_svg = self._visible(qr_svg_locator)
        qr_svg_size = qr_svg.size

        visible_text = self._driver.find_element(By.TAG_NAME, "body").text
        if self.state.person_id and self.state.person_id in visible_text:
            raise AssertionError(
                "The rendered QR state exposed Alex's internal person identifier."
            )
        if not qr_card.is_displayed():
            raise AssertionError(
                "The one-time QR payload label was visible but its QR card was not."
            )
        if not qr_svg.is_displayed():
            raise AssertionError("The one-time QR payload label was visible but its QR SVG was not.")
        if qr_svg_size["width"] < 100 or qr_svg_size["height"] < 100:
            raise AssertionError(
                "The visible QR SVG did not have meaningful rendered dimensions: "
                f"{qr_svg_size['width']}x{qr_svg_size['height']}."
            )

        self._driver.save_screenshot(
            str(self.state.artifact_directory / "step14_qr_success.png")
        )
        self._write_text("step14_qr_success.html", self._driver.page_source)
        self._write_text("step14_qr_success.txt", visible_text)
        self._write_json(
            "step14_qr_success.json",
            {
                "payload_label_visible": payload_label.is_displayed(),
                "qr_card_visible": qr_card.is_displayed(),
                "qr_svg_visible": qr_svg.is_displayed(),
                "qr_svg_dimensions": {
                    "width": qr_svg_size["width"],
                    "height": qr_svg_size["height"],
                },
                "person_id_rendered": False,
                "token_id": self.state.token_id,
            },
        )

    def verify_api_and_audit_evidence(self) -> None:
        """Verify browser-session API state and ordered audit evidence."""
        if self.state.person_id is None or self.state.visit_id is None:
            raise AssertionError("Person or visit identifier was unavailable for API evidence.")
        if self.state.token_id is None:
            raise AssertionError("Token identifier was unavailable for API evidence.")

        training_results = self._browser_api_json(
            f"/api/people/{self.state.person_id}/training-results"
        )
        completed_ids = set(self.state.completed_module_ids.values())
        passed_result_ids = {
            str(result.get("training_module_id"))
            for result in training_results
            if str(result.get("training_module_id")) in completed_ids
            and result.get("outcome") == "passed"
            and result.get("score") == 100
            and result.get("expires_at")
        }
        if passed_result_ids != completed_ids:
            raise AssertionError(
                "The browser-session API did not confirm a current 100% passed "
                f"result for each required module: {passed_result_ids!r}."
            )

        compliance = self._browser_api_json(
            f"/api/visits/{self.state.visit_id}/compliance"
        )
        if compliance.get("eligible") is not True:
            raise AssertionError(f"Compliance was not eligible: {compliance!r}")

        tokens = self._browser_api_json(f"/api/visits/{self.state.visit_id}/tokens")
        issued_token = next(
            (token for token in tokens if str(token.get("id")) == self.state.token_id),
            None,
        )
        if issued_token is None or issued_token.get("status") != "active":
            raise AssertionError("The browser-issued token was not active in token history.")
        if issued_token.get("person_id") is not None:
            raise AssertionError("Token metadata unexpectedly exposed a person identifier.")

        audit_events = self._browser_api_json("/api/audit/events")
        related_actions = [
            str(event.get("action"))
            for event in audit_events
            if event.get("details", {}).get("person_id") == self.state.person_id
            or event.get("details", {}).get("visit_id") == self.state.visit_id
            or str(event.get("entity_id")) == self.state.token_id
        ]
        expected_actions = [
            "training.completed",
            "training.completed",
            "approval.evaluated",
            "approval.approved",
            "token.issued",
        ]
        positions: list[int] = []
        search_start = 0
        for action in expected_actions:
            try:
                position = related_actions.index(action, search_start)
            except ValueError as error:
                raise AssertionError(
                    f"Required Batch 3 audit action {action!r} was absent. "
                    f"Observed related actions: {related_actions!r}"
                ) from error
            positions.append(position)
            search_start = position + 1

        if positions != sorted(positions):
            raise AssertionError(
                "Batch 3 audit actions were not chronological: "
                f"{list(zip(expected_actions, positions))!r}"
            )

        self._write_json(
            "authenticated_browser_api_evidence.json",
            {
                "training_results": training_results,
                "compliance": compliance,
                "issued_token": issued_token,
                "related_audit_actions": related_actions,
                "required_audit_positions": positions,
            },
        )

    def reset_baseline(self, stage: str) -> None:
        """Reset, seed, and health-check the deterministic local Compose baseline."""
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
            self._assert_local_demo_health(health)
            self._write_json(f"{stage}_health.json", health)
        except BaseException:
            self._log_stage("FAIL", stage)
            self._write_text(f"{stage}_error.txt", traceback.format_exc())
            raise
        else:
            self._log_stage("PASS", stage)

    @property
    def _driver(self) -> WebDriver:
        if self.state.driver is None:
            raise RuntimeError("The Chrome driver was not initialized.")
        return self.state.driver

    def _create_driver(self) -> WebDriver:
        """Create a diagnostic-enabled Chrome 153 session for the rendered test."""
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

        chrome_binary = os.environ.get("STEP14_CHROME_BINARY")
        if chrome_binary:
            options.binary_location = chrome_binary

        driver_path = os.environ.get("STEP14_CHROMEDRIVER_PATH")
        service = Service(executable_path=driver_path) if driver_path else Service()
        driver = webdriver.Chrome(service=service, options=options)
        driver.set_page_load_timeout(LONG_WAIT_SECONDS)
        return driver

    def _record_browser_versions(self) -> None:
        """Record and enforce the expected compatible Chrome/ChromeDriver major."""
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
                "STEP-14 requires the compatible Chrome/ChromeDriver "
                f"{EXPECTED_CHROME_MAJOR} pair; found Chrome={browser_version!r}, "
                f"ChromeDriver={driver_version!r}."
            )

    def _run_stage(self, stage: str, action: Callable[[], T]) -> T:
        """Log a stage, immediately capture failure diagnostics, and preserve progress."""
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

    def _wait(self, seconds: int = SHORT_WAIT_SECONDS) -> WebDriverWait:
        return WebDriverWait(self._driver, seconds)

    def _visible(self, locator: tuple[str, str]) -> Any:
        self.state.last_selector = self._selector_text(locator)
        return self._wait().until(expected.visibility_of_element_located(locator))

    def _click(self, locator: tuple[str, str], description: str) -> None:
        self.state.last_selector = self._selector_text(locator)
        element = self._wait().until(expected.element_to_be_clickable(locator))
        element.click()
        self.logger.info(
            "%s Clicked %s using %s",
            STAGE_PREFIX,
            description,
            self.state.last_selector,
        )

    def _matching_passed_result(self, module_id: str) -> list[dict[str, Any]] | bool:
        """Return current matching passed results only after the rendered mutation commits."""
        if self.state.person_id is None:
            raise AssertionError("Alex's identifier was unavailable for training check.")
        results = self._browser_api_json(
            f"/api/people/{self.state.person_id}/training-results"
        )
        matches = [
            result
            for result in results
            if str(result.get("training_module_id")) == module_id
            and result.get("outcome") == "passed"
            and result.get("score") == 100
            and result.get("expires_at")
        ]
        return results if matches else False

    def _active_visit_tokens(self) -> list[dict[str, Any]] | bool:
        """Return active visit tokens only after issue succeeds through the UI."""
        if self.state.visit_id is None:
            raise AssertionError("Selected visit identifier was unavailable for token check.")
        tokens = self._browser_api_json(f"/api/visits/{self.state.visit_id}/tokens")
        active_tokens = [token for token in tokens if token.get("status") == "active"]
        return active_tokens if active_tokens else False

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
        """Persist UTF-8-safe failure/success diagnostics without masking failures."""
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
                "current_url": driver.current_url,
                "person_id": self.state.person_id,
                "visit_id": self.state.visit_id,
                "token_id": self.state.token_id,
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
            self._write_json(f"{prefix}_console.json", self._browser_console_errors())
            self._write_json(f"{prefix}_network.json", self._network_errors())
        except WebDriverException as diagnostic_error:
            self._write_text(
                f"{prefix}_diagnostic_capture_error.txt",
                f"{type(diagnostic_error).__name__}: {diagnostic_error}",
            )

    def _browser_console_errors(self) -> list[dict[str, Any]]:
        """Collect browser console entries when the driver exposes diagnostic logs."""
        try:
            return list(self._driver.get_log("browser"))
        except WebDriverException as error:
            return [{"diagnostic_unavailable": str(error)}]

    def _network_errors(self) -> list[dict[str, Any]]:
        """Collect failed network response metadata from Chrome performance logs."""
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

    def _find_from_selector_text(self, selector: str) -> Any | None:
        try:
            by, value = selector.split("=", 1)
            return self._driver.find_element(by, value)
        except (ValueError, WebDriverException):
            return None

    def _run_compose_command(self, arguments: list[str], output_path: Path) -> None:
        """Run one non-interactive Compose recovery command and retain its output."""
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
        """Poll the API health endpoint until reset/reseed is fully ready."""
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
        raise AssertionError("The API did not return healthy after reset/reseed.") from last_error

    @staticmethod
    def _assert_local_demo_health(health: dict[str, Any]) -> None:
        """Validate that cleanup restored the expected DEMO/LOCAL service modes."""
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
        """Return the repository root from the persisted test-file location."""
        return Path(__file__).resolve().parents[2]

    @staticmethod
    def _selector_text(locator: tuple[str, str]) -> str:
        """Render a Selenium locator in the diagnostics format."""
        return f"{locator[0]}={locator[1]}"

    @staticmethod
    def _xpath_literal(value: str) -> str:
        """Quote arbitrary text safely for an XPath literal."""
        if "'" not in value:
            return f"'{value}'"
        if '"' not in value:
            return f'"{value}"'
        parts = value.split("'")
        return "concat(" + ", \"'\", ".join(f"'{part}'" for part in parts) + ")"

    def _log_stage(self, outcome: str, stage: str) -> None:
        """Emit the required concise stage status line."""
        self.logger.info("%s %s %s", STAGE_PREFIX, outcome, stage)

    def _write_text(self, file_name: str, content: str) -> None:
        """Write diagnostics safely regardless of platform default encoding."""
        (self.state.artifact_directory / file_name).write_text(
            content,
            encoding="utf-8",
            errors="replace",
        )

    def _write_json(self, file_name: str, payload: Any) -> None:
        """Write structured diagnostics using UTF-8 and redaction-safe formatting."""
        self._write_text(
            file_name,
            json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        )


def parse_arguments() -> argparse.Namespace:
    """Parse non-interactive execution options for repeatable validation cycles."""
    parser = argparse.ArgumentParser(
        description="Run durable STEP-14 training-to-QR browser validation cycles."
    )
    parser.add_argument(
        "--runs",
        default=2,
        type=int,
        help="Number of clean workflow cycles to run; use at least two for STEP-14.",
    )
    parser.add_argument(
        "--headed",
        action="store_true",
        help="Show Chrome instead of the default non-interactive headless mode.",
    )
    parser.add_argument(
        "--web-base-url",
        default=DEFAULT_WEB_BASE_URL,
        help="Rendered web application base URL.",
    )
    parser.add_argument(
        "--api-base-url",
        default=DEFAULT_API_BASE_URL,
        help="API base URL used for browser-session assertions and cleanup health.",
    )
    parser.add_argument(
        "--artifacts-dir",
        type=Path,
        default=Path("artifacts") / "step14",
        help="Directory in which isolated run diagnostics are stored.",
    )
    arguments = parser.parse_args()
    if arguments.runs < 2:
        parser.error("--runs must be at least 2 to satisfy the STEP-14 repeatability gate.")
    return arguments


def main() -> int:
    """Run clean STEP-14 browser cycles and return a CI-friendly exit status."""
    arguments = parse_arguments()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    for cycle_number in range(1, arguments.runs + 1):
        validation = Step14BrowserValidation(
            artifact_root=arguments.artifacts_dir,
            web_base_url=arguments.web_base_url,
            api_base_url=arguments.api_base_url,
            headless=not arguments.headed,
            cycle_number=cycle_number,
        )
        try:
            validation.run()
        except (AssertionError, TimeoutException, WebDriverException, RuntimeError):
            logging.exception(
                "%s FAIL workflow cycle %s; diagnostics saved under %s",
                STAGE_PREFIX,
                cycle_number,
                validation.state.artifact_directory,
            )
            return 1
        except BaseException:
            logging.exception(
                "%s FAIL unexpected cycle %s error; diagnostics saved under %s",
                STAGE_PREFIX,
                cycle_number,
                validation.state.artifact_directory,
            )
            return 1

        logging.info(
            "%s PASS workflow cycle %s; artifacts saved under %s",
            STAGE_PREFIX,
            cycle_number,
            validation.state.artifact_directory,
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
