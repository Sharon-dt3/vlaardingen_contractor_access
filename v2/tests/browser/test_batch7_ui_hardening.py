#!/usr/bin/env python3
"""Focused rendered-UI validation for Batch 7 accessibility hardening.

Run from the repository root once the local application is healthy:

    python tests/browser/test_batch7_ui_hardening.py

The check exercises only the hardened UI contracts:
- responsive navigation exposes dialog semantics, Escape dismissal, and focus return;
- a role without gate access receives accessible, API-authority permission feedback; and
- a real server decision is announced before the operator can recover to a new scan.

It does not reset data or alter application state beyond recording one normal gate
evaluation, so it can run safely beside the broader deterministic browser workflows.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from threading import Thread
from typing import Callable, TypeVar

try:
    from selenium import webdriver
    from selenium.common.exceptions import TimeoutException, WebDriverException
    from selenium.webdriver import ChromeOptions
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys
    from selenium.webdriver.remote.webdriver import WebDriver, WebElement
    from selenium.webdriver.support import expected_conditions as expected
    from selenium.webdriver.support.select import Select
    from selenium.webdriver.support.ui import WebDriverWait
except ImportError as error:  # pragma: no cover - execution environment guard
    raise SystemExit(
        "Batch 7 browser validation requires Selenium. Install the approved "
        "browser-test dependency before running this script."
    ) from error


STAGE_PREFIX = "[BATCH-7]"
DEFAULT_WEB_BASE_URL = os.environ.get(
    "BATCH7_WEB_BASE_URL",
    "http://localhost:3000",
)
DEFAULT_DEMO_PASSWORD = os.environ.get(
    "BATCH7_DEMO_PASSWORD",
    "renewi-demo-access",
)
DEFAULT_WAIT_SECONDS = int(os.environ.get("BATCH7_WAIT_SECONDS", "20"))
DRIVER_CLEANUP_TIMEOUT_SECONDS = 5.0
T = TypeVar("T")


@dataclass(frozen=True)
class ValidationConfig:
    """Configuration for one non-interactive Batch 7 validation run."""

    web_base_url: str
    artifact_directory: Path
    headless: bool


class Batch7UiHardeningValidation:
    """Validate the critical user-visible contracts added by Batch 7."""

    def __init__(self, config: ValidationConfig) -> None:
        self.config = config
        self.driver: WebDriver | None = None
        self.current_stage = "initialization"
        self.config.artifact_directory.mkdir(parents=True, exist_ok=True)
        self.logger = logging.getLogger("batch7.ui-hardening")

    def run(self) -> None:
        """Execute all focused checks using independent authenticated sessions."""
        try:
            self._run_stage(
                "responsive-navigation-accessibility",
                self._verify_responsive_navigation_accessibility,
            )
            self._run_stage(
                "permission-feedback",
                self._verify_permission_feedback,
            )
            self._run_stage(
                "server-confirmed-recovery",
                self._verify_server_confirmed_recovery,
            )
        finally:
            self._close_driver()

    def _verify_responsive_navigation_accessibility(self) -> None:
        """Verify mobile dialog state, Escape dismissal, and focus restoration."""
        self._start_session(width=390, height=844)
        self._login("admin.demo")

        menu_button = self._click((By.CSS_SELECTOR, "button[aria-label='Open navigation']"))
        self._wait().until(
            expected.presence_of_element_located(
                (By.CSS_SELECTOR, "#mobile-navigation[role='dialog'][aria-modal='true']")
            )
        )

        assert menu_button.get_attribute("aria-controls") == "mobile-navigation"
        assert menu_button.get_attribute("aria-expanded") == "true"

        close_button = self._wait().until(
            expected.element_to_be_clickable(
                (By.CSS_SELECTOR, "#mobile-navigation button[aria-label='Close navigation']")
            )
        )
        self._wait().until(
            lambda current_driver: current_driver.execute_script(
                "return document.activeElement === arguments[0];",
                close_button,
            )
        )

        self.driver.switch_to.active_element.send_keys(Keys.ESCAPE)
        self._wait().until(
            expected.invisibility_of_element_located((By.ID, "mobile-navigation"))
        )
        self._wait().until(
            lambda current_driver: menu_button.get_attribute("aria-expanded") == "false"
        )
        self._wait().until(
            lambda current_driver: current_driver.execute_script(
                "return document.activeElement === arguments[0];",
                menu_button,
            )
        )

    def _verify_permission_feedback(self) -> None:
        """Verify an unauthorized role receives explanatory, accessible route feedback."""
        self._start_session()
        self._login("viewer.demo")
        self.driver.get(f"{self.config.web_base_url}/gate")

        permission_state = self._visible(
            (
                By.XPATH,
                "//section[@role='status'][.//h2[normalize-space()='Access is restricted']]",
            )
        )
        description = permission_state.text
        return_link = permission_state.find_element(
            By.XPATH,
            ".//a[normalize-space()='Return to overview']",
        )

        assert permission_state.get_attribute("aria-live") == "polite"
        assert permission_state.get_attribute("aria-atomic") == "true"
        assert "Read-only Viewer role does not include access to this area." in description
        assert "API will continue to enforce this restriction" in description
        assert return_link.get_attribute("href").rstrip("/").endswith(
            self.config.web_base_url.rstrip("/")
        )

    def _verify_server_confirmed_recovery(self) -> None:
        """Verify a real gate denial is announced and can safely return to scanning."""
        self._start_session()
        self._login("gate.demo")
        self.driver.get(f"{self.config.web_base_url}/gate")

        site_selector = self._visible((By.ID, "gate-site"))
        self._wait().until(
            lambda current_driver: len(
                site_selector.find_elements(By.CSS_SELECTOR, "option[value]:not([value=''])")
            )
            > 0
        )
        Select(site_selector).select_by_index(1)
        Select(self._visible((By.ID, "gate-scenario"))).select_by_value("sofia")

        self._click(
            (
                By.XPATH,
                "//button[normalize-space()='Simulate camera scan']",
            )
        )
        self._visible(
            (
                By.XPATH,
                "//h2[normalize-space()='Verify gate presentation']",
            )
        )

        self._click((By.XPATH, "//button[normalize-space()='Evaluate at gate']"))
        announcement = self._wait().until(
            expected.presence_of_element_located(
                (
                    By.CSS_SELECTOR,
                    "p[role='status'][aria-live='assertive'][aria-atomic='true']",
                )
            )
        )
        decision_heading = self._visible(
            (
                By.XPATH,
                "//h2[@id='gate-decision' and normalize-space()='Access denied']",
            )
        )

        assert announcement.get_attribute("role") == "status"
        assert announcement.get_attribute("aria-live") == "assertive"
        assert announcement.get_attribute("aria-atomic") == "true"
        assert "sr-only" in announcement.get_attribute("class").split()
        assert announcement.text.startswith("Server decision: access denied.")
        assert decision_heading.is_displayed()
        self._visible(
            (
                By.XPATH,
                "//h3[normalize-space()='Required corrective action']",
            )
        )

        self._click((By.XPATH, "//button[normalize-space()='Start a new scan']"))
        self._visible(
            (
                By.XPATH,
                "//h2[normalize-space()='Scan an access token']",
            )
        )

    def _start_session(self, width: int = 1440, height: int = 900) -> None:
        """Start an isolated browser session so roles and viewport state never leak."""
        self._close_driver()

        options = ChromeOptions()
        if self.config.headless:
            options.add_argument("--headless=new")
        options.add_argument(f"--window-size={width},{height}")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--no-sandbox")

        chrome_binary = os.environ.get("BATCH7_CHROME_BINARY")
        if chrome_binary:
            options.binary_location = chrome_binary

        driver_path = os.environ.get("BATCH7_CHROMEDRIVER_PATH")
        service = Service(executable_path=driver_path) if driver_path else Service()
        self.driver = webdriver.Chrome(service=service, options=options)
        self.driver.set_page_load_timeout(DEFAULT_WAIT_SECONDS)
        self.driver.set_window_size(width, height)

    def _login(self, handle: str) -> None:
        """Authenticate through the rendered demo login form as the supplied role."""
        driver = self._require_driver()
        driver.get(f"{self.config.web_base_url}/login")

        handle_input = self._visible((By.ID, "handle"))
        password_input = self._visible((By.ID, "password"))
        handle_input.clear()
        handle_input.send_keys(handle)
        password_input.clear()
        password_input.send_keys(DEFAULT_DEMO_PASSWORD)

        self._click((By.CSS_SELECTOR, "form button[type='submit']"))
        self._wait().until(lambda current_driver: "/login" not in current_driver.current_url)
        self._wait().until(
            expected.presence_of_element_located(
                (By.XPATH, "//*[contains(normalize-space(), 'Renewi Access')]")
            )
        )

    def _run_stage(self, stage: str, action: Callable[[], T]) -> T:
        """Run a check and capture an image when it fails for actionable CI diagnostics."""
        self.current_stage = stage
        self.logger.info("%s START %s", STAGE_PREFIX, stage)
        try:
            result = action()
        except BaseException:
            self._capture_failure_screenshot()
            self.logger.exception("%s FAIL %s", STAGE_PREFIX, stage)
            raise
        self.logger.info("%s PASS %s", STAGE_PREFIX, stage)
        return result

    def _wait(self) -> WebDriverWait:
        """Return the standard explicit wait for rendered UI transitions."""
        return WebDriverWait(self._require_driver(), DEFAULT_WAIT_SECONDS)

    def _visible(self, locator: tuple[str, str]) -> WebElement:
        """Wait for and return a visible UI element."""
        return self._wait().until(expected.visibility_of_element_located(locator))

    def _click(self, locator: tuple[str, str]) -> WebElement:
        """Wait for a control to become interactive, click it, and return it."""
        element = self._wait().until(expected.element_to_be_clickable(locator))
        element.click()
        return element

    def _capture_failure_screenshot(self) -> None:
        """Persist a screenshot only when a rendered assertion fails."""
        if self.driver is None:
            return

        safe_stage = self.current_stage.replace("/", "-").replace(" ", "-")
        screenshot = self.config.artifact_directory / f"{safe_stage}-failure.png"
        try:
            self.driver.save_screenshot(str(screenshot))
        except WebDriverException:
            self.logger.exception(
                "%s Could not capture failure screenshot for %s",
                STAGE_PREFIX,
                self.current_stage,
            )

    def _close_driver(self) -> None:
        """Close a browser session without allowing a hung driver to block validation."""
        driver = self.driver
        if driver is None:
            return

        # Clear the active reference first so a timed-out quit cannot leak state into
        # the next independent browser session.
        self.driver = None

        def quit_driver() -> None:
            try:
                driver.quit()
            except WebDriverException:
                self.logger.exception("%s Browser cleanup failed", STAGE_PREFIX)

        cleanup_thread = Thread(
            target=quit_driver,
            daemon=True,
            name="batch7-webdriver-cleanup",
        )
        try:
            cleanup_thread.start()
            cleanup_thread.join(DRIVER_CLEANUP_TIMEOUT_SECONDS)
        except RuntimeError:
            self.logger.exception("%s Browser cleanup could not start", STAGE_PREFIX)
            return

        if cleanup_thread.is_alive():
            self.logger.error(
                "%s Browser cleanup exceeded %.1f seconds; continuing validation",
                STAGE_PREFIX,
                DRIVER_CLEANUP_TIMEOUT_SECONDS,
            )

    def _require_driver(self) -> WebDriver:
        """Return the active driver or explain the invalid validation lifecycle."""
        if self.driver is None:
            raise RuntimeError("A browser session must be started before interacting with the UI.")
        return self.driver


def parse_arguments() -> argparse.Namespace:
    """Parse non-interactive browser validation options."""
    parser = argparse.ArgumentParser(
        description="Run focused Batch 7 UI-hardening browser checks.",
    )
    parser.add_argument(
        "--web-base-url",
        default=DEFAULT_WEB_BASE_URL,
        help="Rendered web application base URL.",
    )
    parser.add_argument(
        "--artifacts-dir",
        type=Path,
        default=Path("artifacts") / "batch7",
        help="Directory for failure-only browser screenshots.",
    )
    parser.add_argument(
        "--headed",
        action="store_true",
        help="Show Chrome instead of using the default non-interactive headless mode.",
    )
    return parser.parse_args()


def main() -> int:
    """Run focused Batch 7 checks and return a CI-friendly exit status."""
    arguments = parse_arguments()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    validation = Batch7UiHardeningValidation(
        ValidationConfig(
            artifact_directory=arguments.artifacts_dir,
            headless=not arguments.headed,
            web_base_url=arguments.web_base_url.rstrip("/"),
        )
    )
    try:
        validation.run()
    except (AssertionError, TimeoutException, WebDriverException, RuntimeError):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
