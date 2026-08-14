import unittest

from apx.bridges.browser import LazyPlaywrightDriver


class LazyPlaywrightDriverTests(unittest.TestCase):
    def test_construction_never_touches_playwright(self):
        # Must not raise/import playwright just from instantiating -- this is
        # exactly the bug that made every `apx` invocation launch a real
        # Chromium process the moment a config declared the browser bridge.
        driver = LazyPlaywrightDriver(headless=True)
        self.assertIsNone(driver._driver)

    def test_close_before_any_use_is_a_safe_no_op(self):
        driver = LazyPlaywrightDriver(headless=True)
        driver.close()  # must not raise even though nothing was ever launched
        self.assertIsNone(driver._driver)

    def test_first_real_call_is_the_only_thing_that_constructs_the_backing_driver(self):
        driver = LazyPlaywrightDriver(headless=True)
        created = []

        class FakeBackingDriver:
            def __init__(self, *, headless=True): created.append(headless)
            def open(self, url): return {"url": url, "title": "fake"}
            def close(self): pass

        import apx.bridges.browser as browser_module
        original = browser_module.PlaywrightDriver
        browser_module.PlaywrightDriver = FakeBackingDriver
        try:
            self.assertEqual(created, [])
            driver.open("https://example.com")
            self.assertEqual(created, [True])
            driver.open("https://example.com/2")  # second call reuses the same backing driver
            self.assertEqual(created, [True])
        finally:
            browser_module.PlaywrightDriver = original


if __name__ == "__main__":
    unittest.main()
