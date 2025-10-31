import json
import re
import time
from pathlib import Path
from typing import Optional, Dict
from urllib.parse import urlencode

import requests
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from drive.folder import FolderDownloader

# Configuration
COOKIE_FILE = Path.home() / ".drive_selenium_cookies.json"
SESSION_FILE = Path.home() / ".drive_session_info.json"
PROFILE_PATH = None
_SHARED_DRIVER = None


class GoogleDriveDownloader:
    """Enhanced Google Drive downloader with backend download support"""

    def __init__(self, cookie_file: Path = COOKIE_FILE, session_file: Path = SESSION_FILE):
        self.cookie_file = cookie_file
        self.session_file = session_file
        self.session = requests.Session()
        self.driver = None
        self.authenticated = False

    def _save_cookies(self, driver):
        """Save cookies to file"""
        try:
            self.cookie_file.parent.mkdir(parents=True, exist_ok=True)
            cookies = driver.get_cookies()
            with self.cookie_file.open("w", encoding="utf-8") as f:
                json.dump(cookies, f, indent=2)
            print(f"🔐 Cookies saved to {self.cookie_file} ({len(cookies)} cookies)")
            return True
        except Exception as e:
            print(f"⚠️ Failed to save cookies: {e}")
            return False

    def _load_cookies_to_session(self) -> bool:
        """Load cookies from file into requests session"""
        if not self.cookie_file.exists():
            print("⚠️ No cookie file found")
            return False

        try:
            with self.cookie_file.open("r", encoding="utf-8") as f:
                cookies = json.load(f)

            if not cookies:
                print("⚠️ Cookie file is empty")
                return False

            # Clear existing cookies
            self.session.cookies.clear()

            # Add cookies to requests session
            for cookie in cookies:
                self.session.cookies.set(
                    name=cookie.get('name'),
                    value=cookie.get('value'),
                    domain=cookie.get('domain', '.google.com'),
                    path=cookie.get('path', '/'),
                    secure=cookie.get('secure', False)
                )

            print(f"✅ Loaded {len(cookies)} cookies into session")
            return True

        except Exception as e:
            print(f"⚠️ Failed to load cookies: {e}")
            return False

    def _validate_session(self) -> bool:
        """Validate if the current session is still active"""
        print("🔍 Validating session...")

        if not self.cookie_file.exists():
            print("⚠️ Cookie file not found")
            return False

        if not self._load_cookies_to_session():
            return False

        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9',
            }

            response = self.session.get(
                'https://drive.google.com/drive/my-drive',
                headers=headers,
                timeout=15,
                allow_redirects=True
            )

            # ✅ FIX: If session expired, re-authenticate and reload session
            if 'accounts.google.com' in response.url:
                print("⚠️ Session expired - re-authenticating...")
                if self._authenticate_with_browser():
                    print("✅ Session restored successfully")
                    return True
                else:
                    print("❌ Failed to restore session")
                    return False

            if 'drive.google.com' in response.url and response.status_code == 200:
                self.authenticated = True
                print("✅ Session is valid")
                return True

            print("⚠️ Unexpected response from Drive")
            return False

        except Exception as e:
            print(f"⚠️ Session validation failed: {e}")
            return False

    def _get_webdriver(self, headless: bool = False):
        """Initialize WebDriver for authentication"""
        try:
            from webdriver_manager.chrome import ChromeDriverManager
            from selenium.webdriver.chrome.service import Service

            options = webdriver.ChromeOptions()
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

            service = Service(ChromeDriverManager().install())
            driver = webdriver.Chrome(service=service, options=options)
            driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

            print(f"✅ Chrome WebDriver initialized")
            return driver

        except Exception as e:
            print(f"❌ Chrome initialization failed: {e}")
            raise

    def _authenticate_with_browser(self, return_driver: bool = False):
        """Authenticate using browser and save cookies

        Args:
            return_driver: If True, return the authenticated driver instead of closing it
        """
        print("\n" + "=" * 60)
        print("🔐 AUTHENTICATION REQUIRED")
        print("=" * 60)

        try:
            self.driver = self._get_webdriver(headless=False)
            self.driver.get("https://drive.google.com")
            time.sleep(3)

            # Check if already logged in
            if self._is_logged_in(self.driver):
                print("✅ Already logged in")
                self._save_cookies(self.driver)
                self._load_cookies_to_session()
                self.authenticated = True

                if return_driver:
                    return self.driver
                else:
                    self.driver.quit()
                    self.driver = None
                    return True

            print("➡️ Please log in to Google Drive...")
            print("⏳ Waiting for login (120 seconds timeout)...")

            # Wait for login with extended timeout
            if not self._wait_for_login(self.driver, timeout=120):
                print("❌ Login timeout")
                if not return_driver:
                    self.driver.quit()
                    self.driver = None
                return False

            print("✅ Login successful!")

            # Wait a bit more to ensure all cookies are set
            time.sleep(5)  # Increased from 3 to 5

            self._save_cookies(self.driver)

            # Reload cookies into session
            self._load_cookies_to_session()
            self.authenticated = True

            if return_driver:
                return self.driver
            else:
                self.driver.quit()
                self.driver = None
                return True

        except Exception as e:
            print(f"❌ Authentication failed: {e}")
            if not return_driver and self.driver:
                try:
                    self.driver.quit()
                except:
                    pass
                self.driver = None
            return False

    def _is_logged_in(self, driver, timeout: int = 8) -> bool:
        """Check if user is logged into Google Drive"""
        try:
            current_url = driver.current_url.lower()
            if "accounts.google.com" in current_url and ("signin" in current_url or "servicelogin" in current_url):
                return False

            drive_selectors = [
                'div[role="main"]',
                'c-wiz',
                'div[data-id]',
                'div[guidedhelpid]',
            ]

            for selector in drive_selectors:
                try:
                    element = WebDriverWait(driver, timeout).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, selector))
                    )
                    if element and "servicelogin" not in current_url:
                        return True
                except TimeoutException:
                    continue

            return False

        except Exception:
            return False

    def _wait_for_login(self, driver, timeout: int = 120) -> bool:
        """Wait for user to complete login"""
        start_time = time.time()

        while time.time() - start_time < timeout:
            if self._is_logged_in(driver):
                return True
            time.sleep(2)

        return False

    def _extract_file_id(self, url: str) -> Optional[str]:
        """Extract file ID from Google Drive URL"""
        patterns = [
            r'/file/d/([a-zA-Z0-9_-]+)',
            r'/folders/([a-zA-Z0-9_-]+)',
            r'[?&]id=([a-zA-Z0-9_-]+)',
            r'/open\?id=([a-zA-Z0-9_-]+)',
        ]

        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)

        return None

    def _is_folder(self, url: str) -> bool:
        """Check if URL is a folder"""
        return '/folders/' in url.lower() or '/drive/folders/' in url.lower()

    def _parse_download_form(self, html_content: str) -> Optional[Dict]:
        """Parse the virus scan warning form to extract download parameters"""
        try:
            soup = BeautifulSoup(html_content, 'html.parser')

            # Find the download form
            form = soup.find('form', {'id': 'download-form'})
            if not form:
                return None

            # Extract form action and all hidden inputs
            action = form.get('action', '')
            params = {}

            for input_tag in form.find_all('input'):
                name = input_tag.get('name')
                value = input_tag.get('value')
                if name and value:
                    params[name] = value

            return {
                'action': action,
                'params': params
            }
        except Exception as e:
            print(f"⚠️ Error parsing form: {e}")
            return None

    def _download_file_direct(self, file_id: str, output_path: Path, chunk_size: int = 32768) -> bool:
        """Download file directly using authenticated session with large file support"""
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept-Encoding': 'gzip, deflate, br',
                'Connection': 'keep-alive',
                'Referer': 'https://drive.google.com/',
            }

            # Step 1: Initial request to check for virus scan warning
            print(f"🔗 Initiating download request...")
            url = f'https://drive.google.com/uc?export=download&id={file_id}'

            response = self.session.get(url, headers=headers, stream=True, timeout=30)

            # Check content type
            content_type = response.headers.get('Content-Type', '').lower()

            # If HTML response, need to handle form submission
            if 'text/html' in content_type:
                print("⚠️ Received HTML response - checking for download form...")

                # Read the HTML content
                html_content = response.text

                # Check if it's the virus scan warning page
                if 'virus' in html_content.lower() or 'download-form' in html_content:
                    print("🔍 Virus scan warning detected - parsing download form...")

                    # Parse the form
                    form_data = self._parse_download_form(html_content)

                    if form_data:
                        # Build the download URL with all form parameters
                        download_url = form_data['action']
                        params = form_data['params']

                        # Build query string
                        query_string = urlencode(params)
                        full_url = f"{download_url}?{query_string}"

                        print(f"✅ Form parsed - initiating actual download...")

                        # Make the actual download request
                        response = self.session.get(
                            full_url,
                            headers=headers,
                            stream=True,
                            timeout=30,
                            allow_redirects=True
                        )
                    else:
                        print("⚠️ Could not parse download form - trying alternative method...")

                        # Fallback: extract confirm token and try direct download
                        confirm_match = re.search(r'confirm=([a-zA-Z0-9_-]+)', html_content)
                        uuid_match = re.search(r'uuid=([a-zA-Z0-9_-]+)', html_content)

                        if confirm_match or uuid_match:
                            params = {'id': file_id, 'export': 'download'}
                            if confirm_match:
                                params['confirm'] = confirm_match.group(1)
                            if uuid_match:
                                params['uuid'] = uuid_match.group(1)

                            download_url = f"https://drive.usercontent.google.com/download?{urlencode(params)}"
                            response = self.session.get(
                                download_url,
                                headers=headers,
                                stream=True,
                                timeout=30,
                                allow_redirects=True
                            )
                else:
                    print("⚠️ HTML response but no virus scan warning - may be auth issue")
                    if 'accounts.google.com' in html_content:
                        print("❌ Authentication required - session expired")
                        return False

            # Validate response
            if response.status_code != 200:
                print(f"❌ Download failed with status code: {response.status_code}")
                return False

            # Double-check content type after form submission
            content_type = response.headers.get('Content-Type', '').lower()
            if 'text/html' in content_type:
                # Still HTML - check what it is
                preview_content = response.text[:1000]
                if 'accounts.google.com' in preview_content:
                    print("❌ Authentication required - session may have expired")
                    return False
                elif 'quota' in preview_content.lower():
                    print("❌ Download quota exceeded")
                    return False
                elif len(response.content) < 10000:  # Small HTML response
                    print(f"⚠️ Unexpected HTML response:")
                    print(preview_content[:500])
                    return False

            # Extract filename
            filename = None
            if 'Content-Disposition' in response.headers:
                disposition = response.headers['Content-Disposition']
                # Handle both quoted and unquoted filenames
                filename_match = re.search(r'filename\*?=["\']?([^"\';\n]+)', disposition)
                if filename_match:
                    filename = filename_match.group(1).strip().strip('"\'')
                    # Handle RFC 5987 encoding
                    if filename.startswith('UTF-8\'\''):
                        filename = filename[7:]

            if not filename:
                filename = f'download_{file_id}'

            # Clean filename
            filename = filename.replace('/', '_').replace('\\', '_')

            # Ensure output path
            if output_path.is_dir():
                output_file = output_path / filename
            else:
                output_file = output_path

            # Get file size
            total_size = int(response.headers.get('content-length', 0))

            print(f"📥 Downloading: {filename}")
            if total_size:
                print(f"📊 Size: {total_size / (1024 * 1024):.2f} MB")
            else:
                print(f"📊 Size: Unknown (streaming)")

            # Download with progress tracking
            downloaded = 0
            start_time = time.time()
            last_update = start_time

            with open(output_file, 'wb') as f:
                for chunk in response.iter_content(chunk_size=chunk_size):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)

                        # Update progress every second
                        current_time = time.time()
                        if current_time - last_update >= 1.0:
                            elapsed = current_time - start_time
                            speed = downloaded / elapsed / (1024 * 1024) if elapsed > 0 else 0

                            if total_size:
                                progress = (downloaded / total_size) * 100
                                eta = (total_size - downloaded) / (downloaded / elapsed) if downloaded > 0 else 0
                                print(f"\r⏳ Progress: {progress:.1f}% | "
                                      f"{downloaded / (1024 * 1024):.2f}/{total_size / (1024 * 1024):.2f} MB | "
                                      f"Speed: {speed:.2f} MB/s | ETA: {eta:.0f}s", end='', flush=True)
                            else:
                                print(f"\r⏳ Downloaded: {downloaded / (1024 * 1024):.2f} MB | Speed: {speed:.2f} MB/s",
                                      end='', flush=True)

                            last_update = current_time

            # Verify download
            if downloaded == 0:
                print(f"\n❌ Downloaded 0 bytes - file may not be accessible")
                output_file.unlink(missing_ok=True)
                return False

            # Final summary
            elapsed = time.time() - start_time
            avg_speed = downloaded / elapsed / (1024 * 1024) if elapsed > 0 else 0

            print(f"\n✅ Download completed!")
            print(f"📁 File: {output_file}")
            print(f"📊 Size: {downloaded / (1024 * 1024):.2f} MB")
            print(f"⏱️ Time: {elapsed:.1f}s")
            print(f"🚀 Speed: {avg_speed:.2f} MB/s")

            return True

        except Exception as e:
            print(f"\n❌ Download failed: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _download_folder_as_zip(self, folder_id: str, output_path: Path, chunk_size: int = 32768) -> bool:
        """Download entire folder as ZIP file using browser automation"""
        try:
            print(f"📦 Downloading folder as ZIP using browser...")

            # First, try backend method for small folders
            if self._try_backend_folder_download(folder_id, output_path):
                return True

            # If backend fails, use browser automation
            print("🌐 Backend download failed - using browser automation...")
            return self._download_folder_with_browser(folder_id, output_path)

        except Exception as e:
            print(f"\n❌ Folder download failed: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _try_backend_folder_download(self, folder_id: str, output_path: Path) -> bool:
        """Use Selenium to extract files, then download via backend"""
        try:
            print(f"🔗 Attempting folder download...")

            # Setup browser if needed
            if not hasattr(self, 'driver') or not self.driver:
                from webdriver_manager.chrome import ChromeDriverManager
                from selenium.webdriver.chrome.service import Service

                options = webdriver.ChromeOptions()
                options.add_argument("--start-maximized")
                options.add_argument("--disable-blink-features=AutomationControlled")
                options.add_experimental_option("excludeSwitches", ["enable-automation"])

                service = Service(ChromeDriverManager().install())
                driver = webdriver.Chrome(service=service, options=options)

                driver.get("https://www.google.com")
                time.sleep(2)

                if not self._load_cookies_to_browser(driver):
                    driver.quit()
                    return False

                driver.get("https://drive.google.com/drive/my-drive")
                time.sleep(5)

                if 'accounts.google.com' in driver.current_url.lower():
                    driver.quit()
                    return False

                self.driver = driver
            else:
                driver = self.driver

            downloader = FolderDownloader(self.session)
            downloader.print_summary()

            return success and len(downloader.downloaded_files) > 0

        except Exception as e:
            print(f"❌ Error: {e}")
            return False

    def _save_zip_response(self, response, folder_id: str, output_path: Path) -> bool:
        """Save ZIP response to file"""
        try:
            # Extract filename
            filename = None
            if 'Content-Disposition' in response.headers:
                disposition = response.headers['Content-Disposition']
                filename_match = re.search(r'filename\*?=["\']?([^"\';\n]+)', disposition)
                if filename_match:
                    filename = filename_match.group(1).strip().strip('"\'')

            if not filename:
                filename = f'folder_{folder_id}.zip'

            if not filename.lower().endswith('.zip'):
                filename = f"{filename}.zip"

            output_file = output_path / filename
            total_size = int(response.headers.get('content-length', 0))

            print(f"📥 Downloading: {filename}")
            if total_size:
                print(f"📊 Size: {total_size / (1024 * 1024):.2f} MB")

            downloaded = 0
            start_time = time.time()

            with open(output_file, 'wb') as f:
                for chunk in response.iter_content(chunk_size=32768):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)

            elapsed = time.time() - start_time
            print(f"\n✅ ZIP download completed!")
            print(f"📁 File: {output_file}")
            print(f"📊 Size: {downloaded / (1024 * 1024):.2f} MB")
            print(f"⏱️ Time: {elapsed:.1f}s")

            return True

        except Exception as e:
            print(f"❌ Error saving ZIP: {e}")
            return False

    def _load_cookies_to_browser(self, driver) -> bool:
        """Load cookies from file into Selenium browser with improved handling"""
        if not self.cookie_file.exists():
            print("⚠️ No cookie file found")
            return False

        try:
            with self.cookie_file.open("r") as f:
                cookies = json.load(f)

            successful_cookies = 0
            failed_cookies = 0
            critical_cookies = []

            for cookie in cookies:
                try:
                    cookie_name = cookie.get('name', '')

                    # Track critical auth cookies
                    if any(x in cookie_name.upper() for x in ['SID', 'HSID', 'SSID', 'APISID', 'SAPISID', '__Secure']):
                        critical_cookies.append(cookie_name)

                    # Clean up cookie data for Selenium
                    cookie_data = {
                        'name': cookie_name,
                        'value': cookie.get('value'),
                    }

                    # Handle domain - this is critical
                    domain = cookie.get('domain', '')
                    if domain:
                        # Selenium requires domain to start with dot for subdomains
                        if not domain.startswith('.') and 'google.com' in domain:
                            domain = '.' + domain
                        cookie_data['domain'] = domain
                    else:
                        # Default to .google.com if no domain specified
                        cookie_data['domain'] = '.google.com'

                    # Path
                    cookie_data['path'] = cookie.get('path', '/')

                    # Secure flag - critical for Google cookies
                    if cookie.get('secure'):
                        cookie_data['secure'] = True

                    # HttpOnly flag
                    if cookie.get('httpOnly'):
                        cookie_data['httpOnly'] = True

                    # SameSite
                    if 'sameSite' in cookie:
                        cookie_data['sameSite'] = cookie['sameSite']

                    # Expiry - handle both formats
                    if 'expiry' in cookie:
                        cookie_data['expiry'] = int(cookie['expiry'])
                    elif 'expirationDate' in cookie:
                        cookie_data['expiry'] = int(cookie['expirationDate'])

                    driver.add_cookie(cookie_data)
                    successful_cookies += 1

                except Exception as e:
                    failed_cookies += 1
                    # Log which critical cookies failed
                    if cookie_name in critical_cookies:
                        print(f"⚠️ CRITICAL: Failed to load auth cookie '{cookie_name}': {e}")
                    continue

            print(f"✅ Loaded {successful_cookies} cookies ({failed_cookies} failed)")

            # Check if we loaded any critical auth cookies
            if successful_cookies == 0:
                print("❌ No cookies loaded successfully")
                return False

            if failed_cookies > 0 and any(c in str(critical_cookies) for c in ['SID', 'HSID']):
                print("⚠️ Warning: Some critical authentication cookies failed to load")

            return successful_cookies > 0

        except Exception as e:
            print(f"⚠️ Error loading cookies: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _download_folder_with_browser(self, folder_id: str, output_path: Path, retry_count: int = 0) -> bool:
        """Download folder using browser automation (most reliable method)"""
        try:
            from webdriver_manager.chrome import ChromeDriverManager
            from selenium.webdriver.chrome.service import Service
            from selenium.webdriver.common.action_chains import ActionChains
            from selenium.webdriver.common.keys import Keys

            print("🌐 Initializing browser for folder download...")

            # Setup Chrome with download directory
            download_path = str(output_path.resolve())

            options = webdriver.ChromeOptions()
            prefs = {
                "download.default_directory": download_path,
                "download.prompt_for_download": False,
                "download.directory_upgrade": True,
                "safebrowsing.enabled": False,
                "profile.default_content_settings.popups": 0,
            }
            options.add_experimental_option("prefs", prefs)
            options.add_argument("--start-maximized")
            options.add_argument("--disable-blink-features=AutomationControlled")
            options.add_experimental_option("excludeSwitches", ["enable-automation"])
            options.add_experimental_option('useAutomationExtension', False)

            # Suppress DevTools and error logs
            options.add_experimental_option('excludeSwitches', ['enable-logging'])
            options.add_argument('--log-level=3')
            options.add_argument('--disable-gpu')

            service = Service(ChromeDriverManager().install())
            driver = webdriver.Chrome(service=service, options=options)
            driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

            try:
                # ✅ CRITICAL FIX: Navigate to google.com (not accounts.google.com) to set base domain
                print("🔑 Loading authentication session...")
                driver.get("https://www.google.com")
                time.sleep(3)

                # ✅ Load cookies using improved method
                cookies_loaded = self._load_cookies_to_browser(driver)

                # ✅ If no cookies loaded, authenticate now
                if not cookies_loaded:
                    if retry_count >= 2:
                        print("❌ Max retry attempts reached")
                        driver.quit()
                        return False

                    print("⚠️ No valid session - authentication required")
                    driver.quit()

                    # ✅ CRITICAL: Get authenticated driver directly (don't close it)
                    print("🔐 Authenticating and reusing browser session...")
                    auth_driver = self._authenticate_with_browser(return_driver=True)

                    if not auth_driver:
                        print("❌ Authentication failed")
                        return False

                    # Use the authenticated driver directly
                    driver = auth_driver
                    print("✅ Reusing authenticated browser session")

                    # Already on Drive, just need to navigate to folder
                    folder_url = f'https://drive.google.com/drive/folders/{folder_id}'
                    print(f"📂 Opening folder: {folder_url}")
                    driver.get(folder_url)
                    time.sleep(8)

                    # Skip verification, we know we're authenticated
                    print("✅ Using active authenticated session")
                else:
                    # ✅ Navigate to Drive to activate session - with longer wait
                    print("🔄 Activating session...")
                    driver.get("https://drive.google.com/drive/my-drive")

                    # ✅ CRITICAL: Wait longer for Drive to fully load and process cookies
                    time.sleep(10)  # Increased from 8 to 10 seconds

                    # ✅ Verify authentication with better logic
                    max_verification_attempts = 5  # Increased from 3 to 5
                    session_valid = False

                    for attempt in range(max_verification_attempts):
                        current_url = driver.current_url.lower()

                        # Check if we're on Drive (not login page)
                        if 'drive.google.com' in current_url and 'accounts.google.com' not in current_url:
                            # Check if we can see Drive UI elements (indicates logged in)
                            try:
                                # Try multiple selectors to confirm Drive loaded
                                ui_loaded = False
                                drive_selectors = [
                                    'div[role="main"]',
                                    'c-wiz',
                                    'div[data-id]',
                                    '[guidedhelpid]',
                                    'div[jscontroller]'
                                ]

                                for selector in drive_selectors:
                                    try:
                                        element = WebDriverWait(driver, 3).until(
                                            EC.presence_of_element_located((By.CSS_SELECTOR, selector))
                                        )
                                        if element:
                                            ui_loaded = True
                                            break
                                    except:
                                        continue

                                if ui_loaded:
                                    print("✅ Session authenticated in browser")
                                    session_valid = True
                                    break
                                else:
                                    if attempt < max_verification_attempts - 1:
                                        print(
                                            f"⏳ Drive UI not loaded yet... (attempt {attempt + 1}/{max_verification_attempts})")
                                        time.sleep(5)
                                        # Try refreshing if stuck
                                        if attempt >= 2:
                                            print("🔄 Refreshing page...")
                                            driver.refresh()
                                            time.sleep(5)
                            except:
                                if attempt < max_verification_attempts - 1:
                                    print(
                                        f"⏳ Waiting for Drive UI... (attempt {attempt + 1}/{max_verification_attempts})")
                                    time.sleep(5)
                                continue
                        elif 'accounts.google.com' in current_url:
                            if attempt < max_verification_attempts - 1:
                                print(f"⏳ Still on login page... (attempt {attempt + 1}/{max_verification_attempts})")
                                time.sleep(30)
                                # Try clicking through any prompts
                                try:
                                    # Look for "Continue" or "Next" buttons
                                    continue_buttons = driver.find_elements(By.XPATH,
                                                                            '//button[contains(., "Continue") or contains(., "Next") or @type="submit"]')
                                    if continue_buttons:
                                        print("🔘 Found continue button, clicking...")
                                        continue_buttons[0].click()
                                        time.sleep(3)
                                except:
                                    pass
                            else:
                                # Last attempt failed
                                break
                        else:
                            # Unknown state
                            if attempt < max_verification_attempts - 1:
                                print(f"⏳ Checking session... (attempt {attempt + 1}/{max_verification_attempts})")
                                time.sleep(5)

                    # If validation failed after all attempts
                    if not session_valid:
                        if retry_count >= 2:
                            print("❌ Max retry attempts reached")
                            driver.quit()
                            return False

                        print("❌ Session not valid - re-authenticating...")
                        driver.quit()

                        # ✅ Get authenticated driver directly
                        print("🔐 Authenticating and reusing browser session...")
                        auth_driver = self._authenticate_with_browser(return_driver=True)

                        if not auth_driver:
                            print("❌ Authentication failed")
                            return False

                        # Use the authenticated driver directly
                        driver = auth_driver
                        print("✅ Reusing authenticated browser session")

                        # Already on Drive, navigate to folder
                        folder_url = f'https://drive.google.com/drive/folders/{folder_id}'
                        print(f"📂 Opening folder: {folder_url}")
                        driver.get(folder_url)
                        time.sleep(8)

                        print("✅ Using active authenticated session")
                    else:
                        # Navigate to folder
                        folder_url = f'https://drive.google.com/drive/folders/{folder_id}'
                        print(f"📂 Opening folder: {folder_url}")
                        driver.get(folder_url)
                        time.sleep(8)  # Increased wait time

                        # ✅ Double-check we're still logged in after folder navigation
                        current_url = driver.current_url.lower()
                        if 'accounts.google.com' in current_url:
                            print("❌ Not logged in - session expired during navigation")
                            driver.quit()
                            return False

                        print("✅ Folder opened in browser")

                print("🖱️ Trying right-click download...")
                try:
                    time.sleep(2)
                    menu_clicked = find_and_click_folder(driver)

                    if menu_clicked:
                        # Look for Download option
                        print("🔍 Looking for Download option...")

                        download_selectors = ['//div[@role="menuitem"]//span[text()="Download"]',
                                              '//div[@role="menuitem"][contains(text(), "Download")]',
                                              '//span[text()="Download"]/ancestor::div[@role="menuitem"]',
                                              '//div[@role="menuitem"]//div[text()="Download"]',

                                              # ✅ Added selectors to handle aria-activedescendant & aria-owns
                                              '//*[@aria-activedescendant and contains(., "Download")]',
                                              '//*[@aria-owns]//*[contains(text(), "Download")]',
                                              '//*[@aria-owns]//div[@role="menuitem" and contains(., "Download")]', ]

                        download_found = False
                        for selector in download_selectors:
                            try:
                                download_option = WebDriverWait(driver, 3).until(
                                    EC.element_to_be_clickable((By.XPATH, selector))
                                )
                                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});",
                                                      download_option)
                                time.sleep(0.3)

                                active = driver.switch_to.active_element
                                active.send_keys(Keys.ARROW_DOWN)  # Move to Download option
                                time.sleep(0.3)
                                active.send_keys(Keys.ENTER)  # Confirm
                                print("✅ Download triggered via keyboard keys")
                                download_found = True
                                print("✅ Clicked Download option")
                            except:
                                continue
                            download_found = True

                        if download_found:
                            if self._wait_for_download_start(output_path, timeout=120):
                                success = self._wait_for_download_complete(output_path, timeout=180)
                                driver.quit()
                                return success

                except Exception as e:
                    print(f"⚠️ Right-click method failed: {e}")

                print("❌ All download methods failed")
                driver.quit()
                return False

            finally:
                try:
                    driver.quit()
                except:
                    pass

        except Exception as e:
            print(f"❌ Browser download failed: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _wait_for_download_start(self, download_path: Path, timeout: int = 30) -> bool:
        """Wait for download to start (temp file appears)"""
        start_time = time.time()

        while time.time() - start_time < timeout:
            # Check for temp download files
            temp_files = list(download_path.glob('*.crdownload')) + \
                         list(download_path.glob('*.tmp')) + \
                         list(download_path.glob('*.part'))

            if temp_files:
                print(f"✅ Download started")
                return True

            time.sleep(1)

        return False

    def _wait_for_download_complete(self, download_path: Path, timeout: int = 300) -> bool:
        """Wait for download to complete"""
        print("⏳ Waiting for download to complete...")
        start_time = time.time()
        last_size = {}
        no_change_count = 0

        # Get initial files
        initial_files = set()
        try:
            initial_files = {f.name for f in download_path.iterdir() if f.is_file() and f.suffix == '.zip'}
        except:
            pass

        while time.time() - start_time < timeout:
            # Check for temp files
            temp_files = list(download_path.glob('*.crdownload')) + \
                         list(download_path.glob('*.tmp')) + \
                         list(download_path.glob('*.part'))

            if temp_files:
                # Download in progress
                for tf in temp_files:
                    try:
                        size = tf.stat().st_size
                        size_mb = size / (1024 * 1024)

                        if tf.name in last_size:
                            if size == last_size[tf.name]:
                                no_change_count += 1
                            else:
                                no_change_count = 0

                        last_size[tf.name] = size
                        elapsed = time.time() - start_time
                        print(f"\r⏳ Downloading: {size_mb:.1f} MB | Elapsed: {elapsed:.0f}s", end='', flush=True)
                    except:
                        pass

                # Check if stuck
                if no_change_count > 30:
                    print("\n⚠️ Download appears stuck")
                    return False

                time.sleep(2)
                continue

            # No temp files - check for completed ZIP
            try:
                current_files = {f.name for f in download_path.iterdir() if f.is_file() and f.suffix == '.zip'}
                new_files = current_files - initial_files

                if new_files:
                    for filename in new_files:
                        filepath = download_path / filename
                        size_mb = filepath.stat().st_size / (1024 * 1024)
                        elapsed = time.time() - start_time

                        print(f"\n✅ Download completed!")
                        print(f"📁 File: {filepath}")
                        print(f"📊 Size: {size_mb:.2f} MB")
                        print(f"⏱️ Time: {elapsed:.1f}s")
                        print(f"🚀 Speed: {size_mb / elapsed:.2f} MB/s")
                        return True
            except Exception as e:
                print(f"\n⚠️ Error checking files: {e}")

            time.sleep(2)

        print("\n❌ Download timeout")
        return False

    def download(self, url: str, output_path: str, force_reauth: bool = False) -> bool:
        """
        Main download method with authentication validation

        Args:
            url: Google Drive URL
            output_path: Local path to save file(s)
            force_reauth: Force re-authentication even if session is valid

        Returns:
            bool: Success status
        """
        print("\n" + "=" * 60)
        print("🚀 GOOGLE DRIVE DOWNLOADER (Backend Mode)")
        print("=" * 60)
        print(f"🔗 URL: {url}")
        print(f"📁 Output: {output_path}")
        print("=" * 60 + "\n")

        # Ensure output path exists
        output_path = Path(output_path).resolve()
        output_path.mkdir(parents=True, exist_ok=True)

        # Extract file ID
        file_id = self._extract_file_id(url)
        if not file_id:
            print("❌ Could not extract file ID from URL")
            return False

        print(f"📋 File ID: {file_id}")

        # Check and validate session
        session_valid = False

        if not force_reauth and self.cookie_file.exists():
            print("🔍 Found existing cookie file, validating session...")
            session_valid = self._validate_session()
        else:
            if force_reauth:
                print("🔄 Force re-authentication requested")
            else:
                print("⚠️ No cookie file found")

        # Authenticate if needed
        if not session_valid:
            print("🔐 Authentication required")
            if not self._authenticate_with_browser():
                print("❌ Authentication failed")
                return False

        # Download based on type
        is_folder = self._is_folder(url)

        print(f"\n📦 Detected: {'FOLDER' if is_folder else 'FILE'}")
        print("⬇️ Starting backend download...\n")

        if is_folder:
            # Always download folders as ZIP (mimics Google Drive UI)
            return self._download_folder_as_zip(file_id, output_path)
        else:
            return self._download_file_direct(file_id, output_path)


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


# Convenience functions
def download_from_drive(url: str, output_path: str,
                        cookie_file: Path = COOKIE_FILE,
                        force_reauth: bool = False) -> bool:
    """
    Download file or folder from Google Drive

    Args:
        url: Google Drive URL
        output_path: Local path to save file(s)
        cookie_file: Path to cookie file for session persistence
        force_reauth: Force re-authentication

    Returns:
        bool: Success status
    """
    downloader = GoogleDriveDownloader(cookie_file=cookie_file)
    return downloader.download(url, output_path, force_reauth=force_reauth)


def batch_download(urls: list, output_path: str,
                   cookie_file: Path = COOKIE_FILE) -> Dict[str, bool]:
    """
    Download multiple files/folders from Google Drive

    Args:
        urls: List of Google Drive URLs
        output_path: Local path to save file(s)
        cookie_file: Path to cookie file for session persistence

    Returns:
        dict: Dictionary mapping URLs to success status
    """
    downloader = GoogleDriveDownloader(cookie_file=cookie_file)
    results = {}

    print("\n" + "=" * 60)
    print("📦 BATCH DOWNLOAD MODE")
    print("=" * 60)
    print(f"📊 Total items: {len(urls)}")
    print("=" * 60 + "\n")

    for i, url in enumerate(urls, 1):
        print(f"\n📥 Download {i}/{len(urls)}")
        print("-" * 60)
        results[url] = downloader.download(url, output_path)

        if i < len(urls):
            print("\n⏳ Waiting 3 seconds before next download...")
            time.sleep(3)

    # Summary
    print("\n" + "=" * 60)
    print("📊 BATCH DOWNLOAD SUMMARY")
    print("=" * 60)
    success_count = sum(1 for v in results.values() if v)
    print(f"✅ Successful: {success_count}/{len(urls)}")
    print(f"❌ Failed: {len(urls) - success_count}/{len(urls)}")
    print("=" * 60)

    return results


# Example usage
if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("GOOGLE DRIVE BACKEND DOWNLOADER v2.4")
    print("=" * 60)
    print("Features:")
    print("  ✅ Cookie-based session validation")
    print("  ✅ Automatic re-authentication")
    print("  ✅ Backend downloads (no browser)")
    print("  ✅ Large file support (900MB+)")
    print("  ✅ Virus scan warning handler")
    print("  ✅ Progress tracking with ETA")
    print("  ✅ Folder download with session reuse")
    print("  ✅ Improved cookie loading (critical auth cookies)")
    print("  ✅ Reuse authenticated browser (no session loss)")
    print("  ✅ Extended wait times & retry logic")
    print("=" * 60 + "\n")

    # Single download
    choice = input("Choose mode:\n1. Single download\n2. Batch download\n3. Force re-authenticate\n> ").strip()

    if choice == "1":
        url = input("\n📎 Enter Google Drive URL: ").strip()
        output = input("📁 Enter output path (default: ./downloads): ").strip() or "./downloads"

        if url:
            success = download_from_drive(url, output)
            print(f"\n{'✅ Success!' if success else '❌ Failed!'}")

    elif choice == "2":
        print("\n📋 Enter URLs (one per line, empty line to finish):")
        urls = []
        while True:
            url = input().strip()
            if not url:
                break
            urls.append(url)

        if urls:
            output = input("\n📁 Enter output path (default: ./downloads): ").strip() or "./downloads"
            results = batch_download(urls, output)

    elif choice == "3":
        url = input("\n📎 Enter Google Drive URL: ").strip()
        output = input("📁 Enter output path (default: ./downloads): ").strip() or "./downloads"

        if url:
            success = download_from_drive(url, output, force_reauth=True)
            print(f"\n{'✅ Success!' if success else '❌ Failed!'}")

    else:
        print("❌ Invalid choice")
