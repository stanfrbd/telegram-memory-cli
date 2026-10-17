"""Optional real-browser checks. See README for local execution instructions."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import urllib.request
from contextlib import contextmanager
from pathlib import Path

import pytest

playwright = pytest.importorskip("playwright.sync_api")
BROWSER = os.environ.get("TGMEM_BROWSER_EXECUTABLE")
pytestmark = pytest.mark.skipif(
    not BROWSER and os.environ.get("TGMEM_BROWSER_TESTS") != "1",
    reason="Set TGMEM_BROWSER_EXECUTABLE for browser tests",
)


@contextmanager
def start_server(folder, token=None):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    command = [
        sys.executable,
        str(Path(__file__).with_name("browser_server.py")),
        str(folder),
        str(port),
    ]
    if token:
        command.append(token)
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    base = f"http://127.0.0.1:{port}"
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        for _ in range(100):
            try:
                opener.open(base, timeout=0.5).close()
                break
            except OSError:
                if process.poll() is not None:
                    raise RuntimeError(process.communicate()[1].decode())
                time.sleep(0.05)
        else:
            raise RuntimeError("Test server did not start")
        yield base
    finally:
        process.terminate()
        process.communicate(timeout=10)


@pytest.fixture
def browser():
    with playwright.sync_playwright() as runtime:
        browser = runtime.chromium.launch(
            executable_path=BROWSER,
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu", "--no-zygote"],
        )
        yield browser
        browser.close()


def expect_notice(page, text):
    playwright.expect(page.locator("#notice")).to_contain_text(text, timeout=15000)


def nav(page, name):
    page.locator(f'nav button[data-view="{name}"]').click()


def wait_for_jobs(page):
    page.wait_for_function(
        "async () => (await (await fetch('/api/jobs')).json()).every(j => !['queued','running'].includes(j.status))"
    )
    # Wait for the UI's own polling to reflect completed jobs.
    playwright.expect(page.locator("#jobs")).to_contain_text("completed", timeout=15000)


def test_desktop_end_to_end(browser, tmp_path):
    with start_server(tmp_path) as base:
        page = browser.new_page(viewport={"width": 1400, "height": 1000})
        errors = []
        failures = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on(
            "response",
            lambda response: (
                failures.append(f"{response.status} {response.url}")
                if response.status >= 400
                else None
            ),
        )
        page.goto(base)
        playwright.expect(page.locator("#results .card")).to_have_count(50)
        page.locator("#next").click()
        playwright.expect(page.locator("#page")).to_have_text("Page 2")
        playwright.expect(page.locator("#results .card")).to_have_count(13)
        page.locator("#previous").click()
        page.locator("#media").select_option("image")
        page.locator("#search-form button").click()
        playwright.expect(page.locator("#results .card")).to_have_count(1)
        playwright.expect(page.locator("#results")).to_contain_text("diagram.png")
        page.locator("#results button").filter(has_text="Favorite").click()
        page.locator("#media").select_option("")
        page.locator("summary").click()
        page.locator("#favorites").check()
        page.locator("#search-form button").click()
        playwright.expect(page.locator("#results .card")).to_have_count(1)
        page.locator("#favorites").uncheck()
        page.locator("#mime").fill("application/pdf")
        page.locator("#query").fill("report")
        page.locator("#search-form button").click()
        playwright.expect(page.locator("#results .card")).to_have_count(50)
        # A download traverses the real API, queue, archive and browser file endpoint.
        page.locator("#results .card").first.get_by_role(
            "button", name="Download ↓", exact=True
        ).click()
        nav(page, "transfers")
        wait_for_jobs(page)
        nav(page, "search")
        page.locator("#query").fill("")
        page.locator("#mime").fill("")
        page.locator("#downloaded").check()
        page.locator("#search-form button").click()
        playwright.expect(page.locator("#results .card")).to_have_count(1)
        with page.expect_download() as download:
            page.get_by_role("button", name="Save to device ↓", exact=True).click()
        assert Path(download.value.path()).read_bytes() == b"%PDF-test fixture"
        page.locator("#downloaded").uncheck()
        nav(page, "channels")
        page.locator("#new-channel").fill("@temporary")
        page.locator("#channel-form button").click()
        playwright.expect(page.locator("#channels")).to_contain_text("@temporary")
        page.locator("#channels .panel").filter(has_text="@temporary").get_by_role(
            "button", name="Remove", exact=True
        ).click()
        playwright.expect(page.locator("#channels")).not_to_contain_text("@temporary")
        nav(page, "discover")
        page.locator("#discover-query").fill("security")
        page.locator("#discover-form button").click()
        playwright.expect(page.locator("#discovery-results")).to_contain_text(
            "Discovered Security", timeout=15000
        )
        page.get_by_role("button", name="Save channel", exact=True).click()
        expect_notice(page, "Source saved")
        nav(page, "channels")
        playwright.expect(page.locator("#channels")).to_contain_text("@discovered_security")
        nav(page, "search")
        page.locator("#query").fill("threat")
        for scope in ["saved", "account", "public"]:
            page.locator("#remote-scope").select_option(scope)
            page.locator("#remote").click()
            nav(page, "transfers")
            wait_for_jobs(page)
            nav(page, "search")
        page.locator("#next").click()
        playwright.expect(page.locator("#page")).to_have_text("Page 2")
        nav(page, "transfers")
        playwright.expect(
            page.get_by_role("button", name="Show returned messages", exact=True)
        ).to_have_count(3, timeout=15000)
        page.get_by_role("button", name="Show returned messages", exact=True).first.click()
        playwright.expect(page.locator("#previous")).to_be_disabled()
        playwright.expect(page.locator("#next")).to_be_disabled()
        playwright.expect(page.locator("#page")).to_have_text("Telegram results")
        nav(page, "upload")
        page.locator("#upload-form [name=channel]").fill("me")
        page.locator("#upload-form [name=caption]").fill("Browser upload test")
        page.locator("#upload-form [name=file]").set_input_files(
            {"name": "browser-test.txt", "mimeType": "text/plain", "buffer": b"fixture"}
        )
        page.locator("#upload-form [name=document]").check()
        page.locator("#upload-form button").click()
        wait_for_jobs(page)
        playwright.expect(page.locator("#jobs")).to_contain_text("browser-test.txt", timeout=15000)
        nav(page, "monitor")
        page.locator("#rule-form [name=query]").fill("threat")
        page.locator("#rule-form [name=interval]").fill("5")
        page.locator("#rule-form button").click()
        playwright.expect(page.locator("#rules")).to_contain_text("threat")
        page.locator("#rules").get_by_role("button", name="Pause", exact=True).click()
        playwright.expect(page.locator("#rules")).to_contain_text("Paused")
        page.locator("#rules").get_by_role("button", name="Run now", exact=True).click()
        page.wait_for_function(
            "async () => (await (await fetch('/api/rules')).json()).length === 1"
        )
        page.wait_for_function(
            "async () => {const rules=await (await fetch('/api/rules')).json();return (await (await fetch('/api/rules/'+rules[0].id+'/hits')).json()).length>0}"
        )
        page.locator("#rules").get_by_role("button", name="View matches", exact=True).click()
        playwright.expect(page.locator("#rule-hits")).to_contain_text("Remote threat")
        hit = page.locator("#rule-hits .card").first
        hit.get_by_role("button", name="☆ Favorite", exact=True).click()
        playwright.expect(hit.get_by_role("button", name="★ Favorited", exact=True)).to_be_visible()
        page.locator("#rules").get_by_role("button", name="View matches", exact=True).click()
        playwright.expect(
            page.locator("#rule-hits .card").first.get_by_role(
                "button", name="★ Favorited", exact=True
            )
        ).to_be_visible()
        page.locator("#rules").get_by_role("button", name="Delete", exact=True).click()
        playwright.expect(page.locator("#rules .card")).to_have_count(0)
        # Untrusted message markup remains inert text, including on later pages.
        nav(page, "search")
        page.locator("#query").fill("")
        page.locator("#search-form button").click()
        page.locator("#next").click()
        playwright.expect(page.locator("#results")).to_contain_text("<img src=x onerror=alert(1)>")
        assert page.locator("#results img").count() == 0
        jobs = page.request.get(base + "/api/jobs").json()
        assert {
            "download",
            "discovery",
            "search",
            "account-search",
            "public-search",
            "upload",
            "monitor",
        } <= {job["kind"] for job in jobs}
        assert all(job["status"] == "completed" for job in jobs), jobs
        assert not errors, errors
        assert not failures, failures
        page.close()


def test_mobile_auth_and_layout(browser, tmp_path):
    with start_server(tmp_path, token="browser-test-token") as base:
        page = browser.new_page(
            viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True
        )
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(base)
        expect_notice(page, "Bearer token")
        page.once("dialog", lambda dialog: dialog.accept("browser-test-token"))
        page.get_by_role("button", name="Set API token", exact=True).click()
        expect_notice(page, "Connection updated")
        playwright.expect(page.locator("#results .card")).to_have_count(50)
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), (
            "Mobile horizontal overflow"
        )
        for section in ["channels", "discover", "monitor", "upload", "search"]:
            nav(page, section)
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), (
                f"Overflow in {section}"
            )
        assert not errors, errors
        page.close()


def test_monitoring_resumes_after_server_restart(browser, tmp_path):
    with start_server(tmp_path) as base:
        page = browser.new_page()
        page.goto(base)
        nav(page, "monitor")
        page.locator("#rule-form [name=query]").fill("threat")
        page.locator("#rule-form button").click()
        playwright.expect(page.locator("#rules")).to_contain_text("threat")
        page.close()
    with start_server(tmp_path) as base:
        page = browser.new_page()
        page.goto(base)
        nav(page, "monitor")
        playwright.expect(page.locator("#rules")).to_contain_text("threat")
        page.wait_for_function("""async () => {
            const rules = await (await fetch('/api/rules')).json();
            return (await (await fetch('/api/rules/' + rules[0].id + '/hits')).json()).length > 0;
        }""")
        page.locator("#rules").get_by_role("button", name="View matches", exact=True).click()
        playwright.expect(page.locator("#rule-hits")).to_contain_text("Remote threat")
        page.close()
