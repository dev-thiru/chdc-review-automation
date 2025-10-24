import json
import os
import platform
import time
from pathlib import Path

from selenium import webdriver
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

COOKIE_FILE = Path.home() / ".drive_selenium_cookies.json"
PROFILE_PATH = None
_SHARED_DRIVER = None  # Shared driver instance for multiple downloads


def get_webdriver(download_path, profile_path=None, headless=False):
    """Return WebDriver with download directory set"""
    try:
        from webdriver_manager.chrome import ChromeDriverManager
        from selenium.webdriver.chrome.service import Service

        # Ensure download path is absolute
        download_path = str(Path(download_path).resolve())

        options = webdriver.ChromeOptions()

        # Critical download settings
        prefs = {
            "download.default_directory": download_path,
            "download.prompt_for_download": False,
            "download.directory_upgrade": True,
            "safebrowsing.enabled": False,
            "profile.default_content_settings.popups": 0,
            "profile.content_settings.exceptions.automatic_downloads.*.setting": 1,
            "plugins.always_open_pdf_externally": True,
        }
        options.add_experimental_option("prefs", prefs)

        options.add_argument("--start-maximized")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--disable-extensions")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option('useAutomationExtension', False)

        if headless:
            options.add_argument("--headless=new")
            options.add_argument("--window-size=1920,1080")

        if profile_path:
            profile_path = str(Path(profile_path).resolve())
            options.add_argument(f"--user-data-dir={profile_path}")
            print(f"📁 Using Chrome profile: {profile_path}")

        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)

        # Remove webdriver flag
        driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

        print(f"✅ Chrome WebDriver initialized")
        print(f"📥 Download directory: {download_path}")
        return driver
    except Exception as e:
        print(f"❌ Chrome failed: {e}")
        raise Exception("❌ No supported browsers found. Install Chrome and webdriver-manager.")


def save_cookies(driver, cookie_file: Path):
    """Save cookies to file"""
    try:
        cookie_file.parent.mkdir(parents=True, exist_ok=True)
        cookies = driver.get_cookies()
        with cookie_file.open("w", encoding="utf-8") as f:
            json.dump(cookies, f, indent=2)
        print(f"🔐 Cookies saved to {cookie_file} ({len(cookies)} cookies)")
    except Exception as e:
        print(f"⚠️ Failed to save cookies: {e}")


def load_cookies(driver, cookie_file: Path):
    """Load cookies from file"""
    if not cookie_file.exists():
        print("⚠️ No cookie file found")
        return False

    try:
        with cookie_file.open("r", encoding="utf-8") as f:
            cookies = json.load(f)

        if not cookies:
            print("⚠️ Cookie file is empty")
            return False

        # Navigate to Google Drive first
        driver.get("https://drive.google.com")
        time.sleep(2)

        # Add each cookie
        loaded_count = 0
        for c in cookies:
            try:
                # Filter valid cookie attributes
                cookie = {}
                for key in ["name", "value", "path", "domain", "secure", "httpOnly"]:
                    if key in c:
                        cookie[key] = c[key]

                # Handle expiry separately
                if "expiry" in c:
                    cookie["expiry"] = int(c["expiry"])

                driver.add_cookie(cookie)
                loaded_count += 1
            except Exception as e:
                pass

        print(f"🔁 Loaded {loaded_count}/{len(cookies)} cookies")

        if loaded_count > 0:
            driver.refresh()
            time.sleep(3)
            return True

        return False

    except Exception as e:
        print(f"⚠️ Failed to load cookies: {e}")
        return False


def is_logged_in_drive(driver, timeout=8):
    """Check if user is logged into Google Drive"""
    try:
        # Check if we're on login page
        current_url = driver.current_url.lower()
        if "accounts.google.com" in current_url and ("signin" in current_url or "servicelogin" in current_url):
            return False

        # Look for Drive UI elements
        drive_selectors = [
            'div[role="main"]',
            'div[data-id]',
            'c-wiz',
            'div[aria-label*="Drive"]',
            'div[role="gridcell"]',
            'div[guidedhelpid]',
            'div.a-nEbBXb',
        ]

        for selector in drive_selectors:
            try:
                element = WebDriverWait(driver, timeout).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, selector))
                )
                if element:
                    if "servicelogin" not in current_url and "accounts.google" not in current_url:
                        return True
            except TimeoutException:
                continue

        return False

    except Exception as e:
        return False


def handle_download_anyway_popup(driver, max_wait=20):
    """
    Handle the 'Download anyway' button that appears when Google Drive
    can't scan files for viruses (large files) or has input[type=submit] download buttons.
    """
    print("⏳ Looking for 'Download anyway' button...")

    button_texts = [
        "Download anyway",
        "Still download",
        "Télécharger quand même",
        "Download",
        "Descargar de todos modos",
    ]

    start_time = time.time()
    found = False

    while time.time() - start_time < max_wait:
        # Check for the warning message first
        try:
            warning = driver.find_element(By.XPATH,
                                          "//*[contains(text(), \"can't scan\") or contains(text(), 'too large') or contains(text(), 'virus')]")
            if warning:
                print("⚠️ Virus scan warning detected!")
        except:
            pass

        # Try to find and click standard buttons
        for btn_text in button_texts:
            xpaths = [
                f"//button[normalize-space()='{btn_text}']",
                f"//button[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), '{btn_text.lower()}')]",
                f"//span[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), '{btn_text.lower()}')]/ancestor::button",
                f"//div[@role='button'][contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), '{btn_text.lower()}')]",
            ]
            for xpath in xpaths:
                try:
                    btn = WebDriverWait(driver, 2).until(
                        EC.element_to_be_clickable((By.XPATH, xpath))
                    )
                    if btn:
                        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", btn)
                        try:
                            btn.click()
                            print(f"✅ Clicked '{btn_text}' button successfully!")
                        except:
                            driver.execute_script("arguments[0].click();", btn)
                            print(f"✅ Clicked '{btn_text}' button via JavaScript!")
                        time.sleep(3)
                        return True
                except:
                    continue

        # NEW: Handle input[type=submit] with id="uc-download-link"
        try:
            input_btn = driver.find_element(By.CSS_SELECTOR, 'input#uc-download-link[type="submit"]')
            if input_btn.is_displayed() and input_btn.is_enabled():
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", input_btn)
                try:
                    input_btn.click()
                    print("✅ Clicked 'Download anyway' input button!")
                except:
                    driver.execute_script("arguments[0].click();", input_btn)
                    print("✅ Clicked 'Download anyway' input button via JavaScript!")
                time.sleep(3)
                return True
        except:
            pass

        # If nothing found, wait a bit and retry
        time.sleep(1)

    print("ℹ️ Not able to find 'Download anyway' button , if present click manually")
    close_current_tab(driver)
    return found


def close_current_tab(driver):
    """Close the current browser tab without closing the entire browser"""
    try:
        # Check if there are multiple tabs
        if len(driver.window_handles) > 1:
            driver.close()  # Close current tab
            driver.switch_to.window(driver.window_handles[0])  # Switch to first remaining tab
            print("🔒 Closed current tab, switched to previous tab")
        else:
            # Only one tab, open a new blank tab before closing
            driver.execute_script("window.open('about:blank', '_blank');")
            time.sleep(0.5)
            driver.switch_to.window(driver.window_handles[1])
            driver.close()
            driver.switch_to.window(driver.window_handles[0])
            print("🔒 Closed download tab, returned to blank tab")
    except Exception as e:
        print(f"⚠️ Could not close tab: {e}")


def wait_for_download(download_path, timeout=900, check_interval=2):
    """Wait for download to complete with better detection"""
    print("\n⏳ Waiting for download to complete...")
    download_path = Path(download_path).resolve()
    start_time = time.time()

    # Get initial file list
    initial_files = set()
    try:
        initial_files = {f.name for f in download_path.iterdir() if f.is_file()}
    except:
        pass

    last_size = {}
    no_change_count = 0

    while True:
        elapsed = time.time() - start_time

        if elapsed > timeout:
            print(f"❌ Download timeout after {timeout}s")
            return False

        time.sleep(check_interval)

        # Check for temporary download files
        temp_extensions = ['*.crdownload', '*.tmp', '*.part', '*.download']
        temp_files = []
        for ext in temp_extensions:
            temp_files.extend(download_path.glob(ext))

        if temp_files:
            # Download in progress
            for tf in temp_files:
                try:
                    size = tf.stat().st_size
                    if tf.name in last_size:
                        if size == last_size[tf.name]:
                            no_change_count += 1
                        else:
                            no_change_count = 0
                    last_size[tf.name] = size

                    print(f"⏳ Downloading: {tf.name} ({size / (1024 * 1024):.1f} MB) - {elapsed:.0f}s elapsed")
                except:
                    pass

            # Check if download is stuck
            if no_change_count > 30:
                print("⚠️ Download appears stuck")
                return False

            continue

        # No temp files - check if new files appeared
        try:
            current_files = {f.name for f in download_path.iterdir() if f.is_file()}
            new_files = current_files - initial_files

            if new_files:
                for filename in new_files:
                    filepath = download_path / filename
                    size_mb = filepath.stat().st_size / (1024 * 1024)
                    print(f"✅ Download completed: {filename} ({size_mb:.1f} MB)")
                return True
            elif elapsed > 10:
                print("⚠️ No new files detected yet...")

        except Exception as e:
            print(f"⚠️ Error checking files: {e}")

        time.sleep(check_interval)

    return False


def detect_drive_item_type(driver):
    """Detect if the current item is a file or folder"""
    time.sleep(2)

    url = driver.current_url.lower()

    # Check URL patterns first
    if "/folders/" in url or "/drive/folders/" in url:
        print("📂 Detected: FOLDER (from URL)")
        return "folder"

    if "/file/d/" in url or "/file/view" in url:
        print("📄 Detected: FILE (from URL)")
        return "file"

    # Check page content
    page_source = driver.page_source.lower()

    # Look for virus scan warning or preview warnings
    if any(text in page_source for text in ["can't scan", "couldn't preview", "too large to preview"]):
        print("📄 Detected: FILE (large file warning)")
        return "file"

    # Check for download button
    try:
        download_btn = driver.find_element(By.XPATH,
                                           '//button[contains(., "Download")] | //div[@role="button"][contains(., "Download")]')
        if download_btn:
            print("📄 Detected: FILE (download button present)")
            return "file"
    except:
        pass

    # Check for folder grid
    try:
        grid_items = driver.find_elements(By.CSS_SELECTOR, 'div[role="gridcell"]')
        if len(grid_items) > 1:
            print("📂 Detected: FOLDER (multiple items)")
            return "folder"
    except:
        pass

    print("📄 Detected: FILE (default)")
    return "file"


def download_file(driver, download_path):
    """Download a single file from Google Drive"""
    print("\n" + "=" * 60)
    print("📄 DOWNLOADING FILE")
    print("=" * 60)

    time.sleep(3)

    # Check for virus scan warning
    try:
        warning = driver.find_element(By.XPATH,
                                      "//*[contains(text(), \"can't scan\") or contains(text(), 'too large')]")
        if warning:
            print("⚠️ Large file detected - can't be scanned for viruses")
    except:
        pass

    # Method 1: Look for download button (primary method for large files)
    download_selectors = [
        # Button selectors
        '//button[contains(translate(., "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "download")]',
        '//button[@aria-label="Download"]',
        'button[aria-label="Download"]',

        # Div with role=button
        '//div[@role="button"][contains(translate(., "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "download")]',
        'div[role="button"][aria-label="Download"]',

        # Span inside button
        '//span[contains(translate(text(), "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "download")]/ancestor::button',
    ]

    print("🔍 Looking for Download button...")
    for selector in download_selectors:
        try:
            if selector.startswith('//'):
                btn = WebDriverWait(driver, 5).until(
                    EC.element_to_be_clickable((By.XPATH, selector))
                )
            else:
                btn = WebDriverWait(driver, 5).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, selector))
                )

            if btn:
                print(f"✅ Found Download button!")

                # Scroll into view
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", btn)
                time.sleep(0.5)

                # Try clicking
                try:
                    btn.click()
                    print("✅ Download button clicked!")
                except:
                    driver.execute_script("arguments[0].click();", btn)
                    print("✅ Download button clicked (via JavaScript)!")

                time.sleep(3)

                # Handle "Download anyway" popup
                handle_download_anyway_popup(driver)

                return wait_for_download(download_path)

        except TimeoutException:
            continue
        except Exception as e:
            continue

    print("⚠️ Direct download button not found, trying menu options...")

    # Method 2: Three-dot menu
    try:
        print("🖱️ Trying three-dot menu...")
        more_actions = [
            'div[aria-label="More actions"]',
            'button[aria-label="More actions"]',
            '//div[@aria-label="More actions"]',
            '//button[@aria-label="More actions"]',
            '//div[@aria-activedescendant][@role="button"]',
            '//button[@aria-owns]',
        ]

        for selector in more_actions:
            try:
                if selector.startswith('//'):
                    btn = WebDriverWait(driver, 3).until(
                        EC.element_to_be_clickable((By.XPATH, selector))
                    )
                else:
                    btn = WebDriverWait(driver, 3).until(
                        EC.element_to_be_clickable((By.CSS_SELECTOR, selector))
                    )

                driver.execute_script("arguments[0].scrollIntoView(true);", btn)
                time.sleep(0.5)
                btn.click()
                time.sleep(2)

                # Use enhanced menu detection
                if find_download_in_menu(driver):
                    time.sleep(3)
                    handle_download_anyway_popup(driver)
                    return wait_for_download(download_path)

            except TimeoutException:
                continue

    except Exception as e:
        print(f"⚠️ Three-dot menu failed: {e}")

    # Method 3: Keyboard shortcut
    try:
        print("⌨️ Trying keyboard shortcut (Ctrl+S)...")
        body = driver.find_element(By.TAG_NAME, 'body')

        if platform.system() == "Darwin":
            ActionChains(driver).key_down(Keys.COMMAND).send_keys('s').key_up(Keys.COMMAND).perform()
        else:
            ActionChains(driver).key_down(Keys.CONTROL).send_keys('s').key_up(Keys.CONTROL).perform()

        time.sleep(3)
        handle_download_anyway_popup(driver)
        return wait_for_download(download_path)

    except Exception as e:
        print(f"⚠️ Keyboard shortcut failed: {e}")

    print("❌ All download methods failed")
    return False


def find_download_in_menu(driver):
    """
    Find and click Download option in an open menu by checking aria-activedescendant and aria-owns
    """
    try:
        # Strategy 1: Check for aria-activedescendant on the menu container
        menu_containers = driver.find_elements(By.XPATH,
                                               '//div[@role="menu"] | //div[@role="listbox"] | //div[contains(@class, "menu")]')

        for menu in menu_containers:
            try:
                # Check aria-activedescendant
                active_id = menu.get_attribute('aria-activedescendant')
                if active_id:
                    print(f"🔍 Found aria-activedescendant: {active_id}")

                # Check aria-owns
                owns_ids = menu.get_attribute('aria-owns')
                if owns_ids:
                    print(f"🔍 Found aria-owns: {owns_ids}")
                    # Try to find elements by these IDs
                    for item_id in owns_ids.split():
                        try:
                            item = driver.find_element(By.ID, item_id)
                            if item and 'download' in item.text.lower():
                                print(f"✅ Found Download option via aria-owns ID: {item_id}")
                                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", item)
                                time.sleep(0.3)
                                try:
                                    item.click()
                                except:
                                    driver.execute_script("arguments[0].click();", item)
                                return True
                        except:
                            continue
            except:
                continue

        # Strategy 2: Look for menuitem elements with Download text
        download_selectors = [
            '//div[@role="menuitem"][normalize-space()="Download"]',
            '//div[@role="menuitem"]//span[normalize-space()="Download"]',
            '//div[@role="menuitem"][contains(translate(., "DOWNLOAD", "download"), "download")]',
            '//span[text()="Download"]/ancestor::div[@role="menuitem"]',
        ]

        for selector in download_selectors:
            try:
                download_option = WebDriverWait(driver, 3).until(
                    EC.element_to_be_clickable((By.XPATH, selector))
                )
                if download_option:
                    print(f"✅ Found Download option")
                    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", download_option)
                    time.sleep(0.3)
                    try:
                        download_option.click()
                    except:
                        driver.execute_script("arguments[0].click();", download_option)
                    return True
            except:
                continue

        return False

    except Exception as e:
        print(f"⚠️ Error finding download in menu: {e}")
        return False


def find_and_click_folder(driver, folder_name=".git"):
    """Find and click on a specific folder (like .git) in the Drive view"""
    print(f"🔍 Looking for folder: {folder_name}")

    try:
        # Wait for content to load - try multiple selectors
        loaded = False
        for selector in ['div[role="gridcell"]', 'div[role="button"]', 'div[data-tooltip]', 'div.h-sb-Ic']:
            try:
                WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, selector))
                )
                loaded = True
                print(f"✅ Page loaded (found {selector})")
                break
            except TimeoutException:
                continue

        if not loaded:
            print("⚠️ Could not confirm page loaded")

        time.sleep(2)

        # Strategy 1: Find by data-tooltip and aria-label (your HTML structure)
        selectors = [
            f'//div[@role="button"][@data-tooltip="{folder_name}"][@aria-label="{folder_name}"]',
            f'//div[@role="button"][@data-tooltip="{folder_name}"]',
            f'//div[@aria-label="{folder_name}"][@role="button"]',
            f'//div[@data-tooltip="{folder_name}"]',
            f'//div[contains(@class, "h-sb-Ic")][@data-tooltip="{folder_name}"]',
            f'//div[contains(@class, "h-sb-Ic")][@aria-label="{folder_name}"]',
        ]

        for selector in selectors:
            try:
                element = WebDriverWait(driver, 5).until(
                    EC.presence_of_element_located((By.XPATH, selector))
                )

                if element:
                    print(f"✅ Found folder: {folder_name} (using {selector[:50]}...)")

                    # Scroll into view
                    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
                    time.sleep(0.5)

                    # Highlight for debugging
                    try:
                        driver.execute_script("arguments[0].style.border='3px solid red'", element)
                    except:
                        pass

                    time.sleep(0.3)

                    # Click to select
                    try:
                        element.click()
                        print(f"✅ Clicked on folder: {folder_name}")
                    except:
                        driver.execute_script("arguments[0].click();", element)
                        print(f"✅ Clicked on folder: {folder_name} (via JavaScript)")

                    time.sleep(2)
                    return True

            except (NoSuchElementException, TimeoutException):
                continue

        # Strategy 2: Find by gridcell structure
        print("⚠️ Trying gridcell structure...")
        gridcell_selectors = [
            f'//div[@role="gridcell"]//div[@data-tooltip="{folder_name}"]',
            f'//div[@role="gridcell"]//div[@aria-label="{folder_name}"]',
            f'//div[@role="gridcell"]//div[text()="{folder_name}"]',
        ]

        for selector in gridcell_selectors:
            try:
                element = driver.find_element(By.XPATH, selector)
                if element:
                    print(f"✅ Found folder in gridcell: {folder_name}")

                    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
                    time.sleep(0.5)

                    # Try to find parent gridcell
                    try:
                        gridcell = element.find_element(By.XPATH, './ancestor::div[@role="gridcell"]')
                        target = gridcell
                    except:
                        target = element

                    try:
                        target.click()
                    except:
                        driver.execute_script("arguments[0].click();", target)

                    time.sleep(2)
                    print(f"✅ Clicked on folder: {folder_name}")
                    return True

            except NoSuchElementException:
                continue

        # Strategy 3: Scan all clickable elements
        print("⚠️ Scanning all clickable elements...")
        all_buttons = driver.find_elements(By.CSS_SELECTOR, 'div[role="button"], div[data-tooltip]')
        print(f"Found {len(all_buttons)} clickable elements")

        for btn in all_buttons:
            try:
                tooltip = btn.get_attribute('data-tooltip')
                aria_label = btn.get_attribute('aria-label')

                if (tooltip and folder_name in tooltip) or (aria_label and folder_name in aria_label):
                    print(f"✅ Found folder by scanning: {folder_name}")

                    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", btn)
                    time.sleep(0.5)

                    try:
                        btn.click()
                    except:
                        driver.execute_script("arguments[0].click();", btn)

                    time.sleep(2)
                    print(f"✅ Clicked on folder: {folder_name}")
                    return True

            except:
                continue

        print(f"❌ Could not find folder: {folder_name}")
        return False

    except Exception as e:
        print(f"❌ Error finding folder: {e}")
        import traceback
        traceback.print_exc()
        return False


def click_three_dot_menu_and_download(driver, download_path):
    """Click the three-dot menu on selected item and download"""
    print("🖱️ Looking for three-dot menu or dropdown...")

    try:
        # After clicking .git folder, we need to click the dropdown arrow
        # From your HTML: <div class="c-Po a-w-d-aa-zd" aria-hidden="true"><svg...>

        time.sleep(2)

        # Strategy 1: Click the dropdown arrow that's part of the .git button
        # This should open the menu with Download option
        dropdown_selectors = [
            # The SVG arrow inside the dropdown div
            '//div[@role="button"][@aria-expanded="false"]//svg[@class="a-s-fa-Ha-pa c-qd"]',
            '//div[@role="button"][@data-tooltip=".git"]//svg',
            '//div[contains(@class, "c-Po")]//svg',
            '//div[@aria-hidden="true"]//svg',
            # Try the parent div
            '//div[@role="button"][@data-tooltip=".git"]//div[contains(@class, "c-Po")]',
            '//div[@role="button"][@aria-expanded="false"]//div[@aria-hidden="true"]',
        ]

        dropdown_opened = False
        for selector in dropdown_selectors:
            try:
                element = WebDriverWait(driver, 3).until(
                    EC.presence_of_element_located((By.XPATH, selector))
                )

                if element:
                    print(f"✅ Found dropdown element")

                    # Scroll into view
                    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
                    time.sleep(0.5)

                    # Try clicking the element or its parent
                    click_target = element
                    try:
                        # Try to get parent button if this is the SVG
                        parent = element.find_element(By.XPATH, './ancestor::div[@role="button"]')
                        click_target = parent
                    except:
                        pass

                    # Click
                    try:
                        click_target.click()
                        print("✅ Clicked dropdown")
                    except:
                        driver.execute_script("arguments[0].click();", click_target)
                        print("✅ Clicked dropdown (via JavaScript)")

                    dropdown_opened = True
                    time.sleep(2)
                    break

            except TimeoutException:
                continue

        # Strategy 2: If the element has aria-expanded, it might expand when clicked
        # Try clicking the .git button itself again to expand it
        if not dropdown_opened:
            print("⚠️ Trying to re-click .git button to expand menu...")
            try:
                git_button = driver.find_element(By.XPATH,
                                                 '//div[@role="button"][@data-tooltip=".git"]')

                if git_button:
                    # Check if it's not expanded
                    expanded = git_button.get_attribute('aria-expanded')
                    if expanded == 'false' or not expanded:
                        driver.execute_script("arguments[0].click();", git_button)
                        print("✅ Re-clicked .git button")
                        dropdown_opened = True
                        time.sleep(2)
            except:
                pass

        # Strategy 3: Look for standard three-dot menu button
        if not dropdown_opened:
            print("⚠️ Trying standard three-dot menu...")
            more_actions_selectors = [
                'div[aria-label="More actions"]',
                'button[aria-label="More actions"]',
                '//div[@aria-label="More actions"]',
                '//button[@aria-label="More actions"]',
                # Near .git element
                '//div[@data-tooltip=".git"]//following::div[@aria-label="More actions"][1]',
                '//div[@data-tooltip=".git"]//parent::*//*[@aria-label="More actions"]',
            ]

            for selector in more_actions_selectors:
                try:
                    if selector.startswith('//'):
                        menu_button = WebDriverWait(driver, 3).until(
                            EC.element_to_be_clickable((By.XPATH, selector))
                        )
                    else:
                        menu_button = WebDriverWait(driver, 3).until(
                            EC.element_to_be_clickable((By.CSS_SELECTOR, selector))
                        )

                    if menu_button:
                        print("✅ Found three-dot menu")
                        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", menu_button)
                        time.sleep(0.5)

                        try:
                            menu_button.click()
                        except:
                            driver.execute_script("arguments[0].click();", menu_button)

                        print("✅ Opened three-dot menu")
                        dropdown_opened = True
                        time.sleep(2)
                        break

                except TimeoutException:
                    continue

        if not dropdown_opened:
            print("❌ Could not open dropdown menu")
            # Debug: Take screenshot if possible
            try:
                driver.save_screenshot("debug_no_dropdown.png")
                print("📸 Screenshot saved to debug_no_dropdown.png")
            except:
                pass
            return False

        # Now find and click Download option in the menu
        print("🔍 Looking for Download option in menu...")

        # Wait a moment for menu to fully appear
        time.sleep(1)

        download_selectors = [
            # Standard menuitem with Download text
            '//div[@role="menuitem"][normalize-space()="Download"]',
            '//div[@role="menuitem"]//span[normalize-space()="Download"]',
            '//div[@role="menuitem"]//span[text()="Download"]',
            '//div[@role="menuitem"][contains(., "Download")]',
            '//span[text()="Download"]/ancestor::div[@role="menuitem"]',
            '//div[@role="menu"]//span[contains(., "Download")]',
            # Broader search
            '//div[@role="menuitem"]',  # Get all menu items and filter
            '//span[text()="Download"]',
            '//div[text()="Download"]',
            # Case insensitive
            '//div[@role="menuitem"][contains(translate(., "DOWNLOAD", "download"), "download")]',
        ]

        for selector in download_selectors:
            try:
                if selector == '//div[@role="menuitem"]':
                    # Special case: get all menu items
                    items = driver.find_elements(By.XPATH, selector)
                    for item in items:
                        try:
                            if 'download' in item.text.lower():
                                print(f"✅ Found Download in menu item: {item.text}")

                                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", item)
                                time.sleep(0.3)

                                try:
                                    item.click()
                                except:
                                    driver.execute_script("arguments[0].click();", item)

                                print("✅ Clicked Download option")
                                time.sleep(0.3)

                                handle_download_anyway_popup(driver)
                                return wait_for_download(download_path)
                        except:
                            continue
                else:
                    download_option = WebDriverWait(driver, 5).until(
                        EC.element_to_be_clickable((By.XPATH, selector))
                    )

                    if download_option:
                        print(f"✅ Found Download option")

                        # Highlight
                        try:
                            driver.execute_script("arguments[0].style.backgroundColor='yellow'", download_option)
                        except:
                            pass

                        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", download_option)
                        time.sleep(0.5)

                        try:
                            download_option.click()
                        except:
                            driver.execute_script("arguments[0].click();", download_option)

                        print("✅ Clicked Download option")
                        time.sleep(3)

                        handle_download_anyway_popup(driver)
                        return wait_for_download(download_path)

            except TimeoutException:
                continue
            except Exception as e:
                continue

        # Debug: Print what we can see
        print("\n⚠️ DEBUG: Could not find Download option")
        try:
            # Try to find any visible text that might be the menu
            visible_text = driver.find_elements(By.XPATH, '//*[contains(text(), "")]')
            print(f"Visible elements: {len(visible_text)}")

            menu_items = driver.find_elements(By.XPATH, '//div[@role="menuitem"] | //div[@role="menu"]//*')
            if menu_items:
                print(f"Found {len(menu_items)} menu items:")
                for item in menu_items[:10]:
                    try:
                        text = item.text.strip()
                        if text:
                            print(f"  - {text}")
                    except:
                        pass

            # Take screenshot for debugging
            driver.save_screenshot("debug_menu_opened.png")
            print("📸 Screenshot saved to debug_menu_opened.png")
        except Exception as e:
            print(f"Debug info failed: {e}")

        return False

    except Exception as e:
        print(f"❌ Error using dropdown menu: {e}")
        import traceback
        traceback.print_exc()
        return False


def download_folder(driver, download_path):
    """Download entire folder from Google Drive"""
    print("\n" + "=" * 60)
    print("📂 DOWNLOADING FOLDER")
    print("=" * 60)

    try:
        # Wait for folder contents - try multiple element types
        print("⏳ Waiting for folder contents...")
        loaded = False

        for selector in ['div[role="gridcell"]', 'div[role="button"]', 'div[data-tooltip]', 'div.h-sb-Ic']:
            try:
                WebDriverWait(driver, 15).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, selector))
                )
                print(f"✅ Folder contents loaded ({selector})")
                loaded = True
                break
            except TimeoutException:
                continue

        if not loaded:
            print("❌ Could not detect folder contents")
            return False

        time.sleep(3)

        # Check if we need to find and click a specific folder (like .git)
        # First check if .git folder exists in current view
        git_folder_exists = False

        try:
            # Try to find .git using the HTML structure from your example
            git_element = driver.find_element(By.XPATH,
                                              '//div[@role="button"][@data-tooltip=".git"] | '
                                              '//div[@data-tooltip=".git"] | '
                                              '//div[@aria-label=".git"]')

            if git_element:
                git_folder_exists = True
                print("📂 Detected .git folder in current view")
        except NoSuchElementException:
            print("ℹ️ No .git folder detected")

        # If .git exists, click it and download via three-dot menu
        if git_folder_exists:
            print("📂 Attempting to download .git folder specifically...")
            if find_and_click_folder(driver, ".git"):
                time.sleep(2)
                return click_three_dot_menu_and_download(driver, download_path)
            else:
                print("⚠️ Failed to click .git, trying default method...")

        # Default behavior: Try to select all and download
        # But first check if we have gridcells (standard Drive view)
        try:
            gridcells = driver.find_elements(By.CSS_SELECTOR, 'div[role="gridcell"]')

            if len(gridcells) > 0:
                print(f"ℹ️ Found {len(gridcells)} items in standard grid view")
                print("🖱️ Selecting all items...")

                # Select all
                if platform.system() == "Darwin":
                    ActionChains(driver).key_down(Keys.COMMAND).send_keys('a').key_up(Keys.COMMAND).perform()
                else:
                    ActionChains(driver).key_down(Keys.CONTROL).send_keys('a').key_up(Keys.CONTROL).perform()

                time.sleep(2)

                # Right-click on first item
                print("⬇️ Opening context menu...")
                try:
                    first_item = driver.find_element(By.CSS_SELECTOR, 'div[role="gridcell"][aria-selected="true"]')
                except:
                    first_item = gridcells[0]

                ActionChains(driver).context_click(first_item).perform()
                time.sleep(2)

                # Click Download
                download_item = WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable((By.XPATH,
                                                '//div[@role="menuitem"][contains(., "Download")]'))
                )
                download_item.click()
                time.sleep(3)

                handle_download_anyway_popup(driver)
                return wait_for_download(download_path)
            else:
                print("⚠️ No standard gridcells found, folder may have different view")

                # Try alternative: look for any clickable items
                clickable_items = driver.find_elements(By.CSS_SELECTOR, 'div[role="button"][data-tooltip]')
                if len(clickable_items) > 0:
                    print(f"ℹ️ Found {len(clickable_items)} clickable items")

                    # If there's only one item and it's .git, download it
                    if len(clickable_items) == 1:
                        item = clickable_items[0]
                        tooltip = item.get_attribute('data-tooltip')
                        if tooltip == '.git':
                            print("📂 Single .git folder detected, downloading it...")
                            item.click()
                            time.sleep(2)
                            return click_three_dot_menu_and_download(driver, download_path)

                    # Otherwise select all and try to download
                    print("🖱️ Attempting to select all items...")
                    if platform.system() == "Darwin":
                        ActionChains(driver).key_down(Keys.COMMAND).send_keys('a').key_up(Keys.COMMAND).perform()
                    else:
                        ActionChains(driver).key_down(Keys.CONTROL).send_keys('a').key_up(Keys.CONTROL).perform()

                    time.sleep(2)

                    # Try right-click on first item
                    ActionChains(driver).context_click(clickable_items[0]).perform()
                    time.sleep(2)

                    # Click Download
                    download_item = WebDriverWait(driver, 10).until(
                        EC.element_to_be_clickable((By.XPATH,
                                                    '//div[@role="menuitem"][contains(., "Download")] | '
                                                    '//span[text()="Download"]/ancestor::div[@role="menuitem"]'))
                    )
                    download_item.click()
                    time.sleep(3)

                    handle_download_anyway_popup(driver)
                    return wait_for_download(download_path)
                else:
                    print("❌ Could not find any items to download")
                    return False

        except Exception as e:
            print(f"❌ Error in default download method: {e}")
            import traceback
            traceback.print_exc()
            return False

    except Exception as e:
        print(f"❌ Folder download failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def download_from_drive(google_drive_link: str, download_path: str,
                        cookie_file: Path = COOKIE_FILE, profile_path: str = None,
                        headless: bool = False, reuse_driver: bool = True):
    """
    Main function to download files/folders from Google Drive

    Args:
        google_drive_link: Google Drive URL
        download_path: Local path to save files
        cookie_file: Path to cookie file for session persistence
        profile_path: Chrome profile path for persistent login
        headless: Run in headless mode
        reuse_driver: Reuse browser instance across multiple calls (recommended)
    """
    global _SHARED_DRIVER

    # Validate inputs
    if not google_drive_link or not google_drive_link.startswith("http"):
        raise ValueError("❌ Invalid Google Drive link")

    # Ensure download path exists and is absolute
    download_path = str(Path(download_path).resolve())
    os.makedirs(download_path, exist_ok=True)

    print("\n" + "=" * 60)
    print("🚀 GOOGLE DRIVE DOWNLOADER")
    print("=" * 60)
    print(f"📁 Download path: {download_path}")
    print(f"🔗 Link: {google_drive_link}")
    print("=" * 60 + "\n")

    # Use shared driver if reuse is enabled and driver exists
    if reuse_driver and _SHARED_DRIVER:
        driver = _SHARED_DRIVER
        print("♻️ Reusing existing browser session\n")
    else:
        driver = get_webdriver(download_path, profile_path, headless)

        # Load cookies if not using profile
        if cookie_file and not profile_path:
            load_cookies(driver, cookie_file)

        # Save driver for reuse
        if reuse_driver:
            _SHARED_DRIVER = driver

    try:
        # Navigate to link
        print(f"🌐 Navigating to link...")
        driver.get(google_drive_link)
        time.sleep(4)

        # Check login (only prompt if really needed)
        if not is_logged_in_drive(driver, timeout=10):
            print("\n" + "=" * 60)
            print("🔐 GOOGLE LOGIN REQUIRED")
            print("=" * 60)
            input("➡️ Please log in and press ENTER...")

            if not is_logged_in_drive(driver, timeout=30):
                print("❌ Login failed")
                return False

            if not profile_path:
                save_cookies(driver, cookie_file)

            print("✅ Login successful!\n")
        else:
            print("✅ Already logged in\n")

        # Detect and download
        item_type = detect_drive_item_type(driver)

        success = False
        if item_type == "folder":
            success = download_folder(driver, download_path)
        else:
            success = download_file(driver, download_path)

        # Status
        print("\n" + "=" * 60)
        if success:
            print("✅ DOWNLOAD COMPLETED!")
        else:
            print("⚠️ DOWNLOAD MAY HAVE ISSUES")
        print("=" * 60 + "\n")

        return success

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


def close_driver():
    """Close the shared driver (call this when done with all downloads)"""
    global _SHARED_DRIVER
    if _SHARED_DRIVER:
        print("\n🔒 Closing browser...")
        try:
            _SHARED_DRIVER.quit()
            _SHARED_DRIVER = None
            print("✅ Browser closed")
        except:
            pass


# Example usage
if __name__ == "__main__":
    # Example for multiple downloads
    print("\n" + "=" * 60)
    print("GOOGLE DRIVE BATCH DOWNLOADER")
    print("=" * 60)

    # Option 1: Single download
    link = input("\n📎 Enter Google Drive link (or press Enter to skip): ").strip()

    if link:
        download_path = input("📁 Enter download path: ").strip() or "./downloads"
        download_from_drive(link, download_path)
        close_driver()
    else:
        # Option 2: Multiple downloads (like your use case)
        print("\n📋 Example: Multiple downloads")
        print("-" * 60)

        base_dir = "./downloads"

        tar_link = input("📎 Enter tar file link: ").strip()
        git_folder_link = input("📎 Enter folder link: ").strip()

        if tar_link and git_folder_link:
            print("\n🚀 Starting batch download...\n")

            # Download 1
            print("📥 Download 1/2: TAR file")
            success1 = download_from_drive(tar_link, base_dir, reuse_driver=True)

            # Download 2 (reuses same browser)
            print("\n📥 Download 2/2: Folder")
            success2 = download_from_drive(git_folder_link, base_dir, reuse_driver=True)

            # Close browser when done
            close_driver()

            print("\n" + "=" * 60)
            print("📊 BATCH DOWNLOAD SUMMARY")
            print("=" * 60)
            print(f"TAR file: {'✅ Success' if success1 else '❌ Failed'}")
            print(f"Folder: {'✅ Success' if success2 else '❌ Failed'}")
            print("=" * 60)
