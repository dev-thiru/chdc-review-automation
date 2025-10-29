import json
import re
import time
from pathlib import Path
from typing import Optional, Dict, List, Tuple
from urllib.parse import urlencode, quote, unquote

import requests
from bs4 import BeautifulSoup


class FolderDownloader:
    """Enhanced folder download with recursive traversal using authenticated session"""

    def __init__(self, session: requests.Session):
        self.session = session
        self.downloaded_files = []
        self.failed_files = []
        self.total_size = 0

    def _extract_key_from_cookies(self) -> Optional[str]:
        """Extract SAPISIDHASH or similar auth key from cookies"""
        try:
            # Try to find SAPISID cookie for authorization
            sapisid = None
            for cookie in self.session.cookies:
                if cookie.name == 'SAPISID':
                    sapisid = cookie.value
                    break

            if sapisid:
                # Generate SAPISIDHASH (simplified - real one uses timestamp + hash)
                import hashlib
                timestamp = str(int(time.time()))
                hash_string = f"{timestamp} {sapisid} https://drive.google.com"
                hash_value = hashlib.sha1(hash_string.encode()).hexdigest()
                return f"SAPISIDHASH {timestamp}_{hash_value}"

            return None
        except:
            return None

    def _get_folder_contents(self, folder_id: str) -> List[Dict]:
        """
        Fetch folder contents using authenticated Drive requests
        Returns list of items with metadata
        """
        try:
            print(f"📂 Fetching contents of folder: {folder_id}")

            # Method 1: Use Drive's query parameter API
            items = self._fetch_via_query_api(folder_id)
            if items:
                print(f"✅ Found {len(items)} items via query API")
                return items

            # Method 2: Parse the folder page HTML
            items = self._fetch_via_html_parsing(folder_id)
            if items:
                print(f"✅ Found {len(items)} items via HTML parsing")
                return items

            # Method 3: Try internal batch API
            items = self._fetch_via_batch_api(folder_id)
            if items:
                print(f"✅ Found {len(items)} items via batch API")
                return items

            print("⚠️ All methods failed to fetch folder contents")
            return []

        except Exception as e:
            print(f"❌ Error fetching folder contents: {e}")
            import traceback
            traceback.print_exc()
            return []

    def _fetch_via_query_api(self, folder_id: str) -> List[Dict]:
        """Fetch using Drive's internal query API"""
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': '*/*',
                'Accept-Language': 'en-US,en;q=0.9',
                'Referer': f'https://drive.google.com/drive/folders/{folder_id}',
                'X-Drive-First-Party': 'DriveWebUi',
                'X-JSON-Requested': 'true',
                'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8',
            }

            # Add authorization if available
            auth_header = self._extract_key_from_cookies()
            if auth_header:
                headers['Authorization'] = auth_header

            # Drive internal API
            api_url = 'https://clients6.google.com/drive/v2beta/files'

            params = {
                'openDrive': 'true',
                'reason': '102',
                'syncType': '0',
                'errorRecovery': 'false',
                'q': f'trashed = false and "{folder_id}" in parents',
                'fields': 'kind,nextPageToken,items(kind,modifiedDate,modifiedByMeDate,lastViewedByMeDate,fileSize,owners(kind,permissionId,id),lastModifyingUser(kind,permissionId,id),hasThumbnail,thumbnailVersion,title,id,resourceKey,shared,sharedWithMeDate,userPermission(role),explicitlyTrashed,mimeType,quotaBytesUsed,copyRequiresWriterPermission,folderColorRgb,hasAugmentedPermissions,spaces(apps),version,teamDriveId,hasChildFolders,trashingUser(kind,permissionId,id),trashedDate,parents(id),shortcutDetails(targetId,targetMimeType,targetLookupStatus),capabilities(canCopy,canDownload,canEdit,canAddChildren,canDelete,canRemoveChildren,canShare,canTrash,canRename,canReadTeamDrive,canMoveTeamDriveItem),labels(starred,trashed,restricted,viewed))',
                'appDataFilter': 'NO_APP_DATA',
                'spaces': 'drive',
                'maxResults': '1000',
                'orderBy': 'folder,title_natural asc',
                'retryCount': '0',
                'key': 'AIzaSyC1eQ1xj69IdTMeii5r7brs3R90eck-m7k',
            }

            response = self.session.get(api_url, params=params, headers=headers, timeout=30)

            if response.status_code == 200:
                try:
                    data = response.json()
                    items = []

                    if 'items' in data:
                        for item in data['items']:
                            items.append({
                                'id': item['id'],
                                'name': item.get('title', 'unnamed'),
                                'mimeType': item.get('mimeType', 'application/octet-stream'),
                                'size': int(item.get('fileSize', 0)) if item.get('fileSize') else 0,
                                'isFolder': item.get('mimeType') == 'application/vnd.google-apps.folder'
                            })

                    return items
                except json.JSONDecodeError:
                    print("⚠️ Failed to parse API response")
                    return []

            return []

        except Exception as e:
            print(f"⚠️ Query API error: {e}")
            return []

    def _fetch_via_html_parsing(self, folder_id: str) -> List[Dict]:
        """Fetch by parsing the Drive folder page HTML"""
        try:
            print("🔄 Trying HTML parsing method...")

            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9',
                'Referer': 'https://drive.google.com/',
                'Connection': 'keep-alive',
            }

            page_url = f'https://drive.google.com/drive/folders/{folder_id}'
            response = self.session.get(page_url, headers=headers, timeout=30)

            if response.status_code != 200:
                print(f"⚠️ HTTP {response.status_code} - Cannot access folder page")
                return []

            html_content = response.text
            items = []

            # Look for embedded JSON data in script tags
            # Google Drive embeds file data in various formats

            # Pattern 1: Look for file data arrays
            # Format: ["file_id","filename","mimetype",...]
            pattern1 = r'\["([a-zA-Z0-9_-]{20,})","([^"]+)","([^"]*application[^"]*)"[^\]]*\]'
            matches = re.findall(pattern1, html_content)

            for match in matches:
                file_id, name, mime = match[0], match[1], match[2]
                if file_id and name and len(file_id) > 20:  # Valid Drive file ID
                    items.append({
                        'id': file_id,
                        'name': name,
                        'mimeType': mime,
                        'size': 0,
                        'isFolder': 'folder' in mime.lower()
                    })

            # Pattern 2: Look for data in window initialization
            pattern2 = r'\[null,\["([a-zA-Z0-9_-]{20,})".*?"([^"]+)".*?"([^"]*)"'
            matches2 = re.findall(pattern2, html_content, re.DOTALL)

            for match in matches2:
                file_id, name = match[0], match[1]
                mime = match[2] if len(match) > 2 else 'application/octet-stream'

                if file_id and name and len(file_id) > 20:
                    # Avoid duplicates
                    if not any(item['id'] == file_id for item in items):
                        items.append({
                            'id': file_id,
                            'name': name,
                            'mimeType': mime,
                            'size': 0,
                            'isFolder': 'folder' in mime.lower()
                        })

            # Pattern 3: Extract from data structure (more complex parsing)
            # Look for: [["file_id",null,null],"filename",[...]]
            pattern3 = r'\[\["([a-zA-Z0-9_-]{20,})"[^\]]*\],"([^"]+)"'
            matches3 = re.findall(pattern3, html_content)

            for match in matches3:
                file_id, name = match[0], match[1]
                if file_id and name and len(file_id) > 20:
                    if not any(item['id'] == file_id for item in items):
                        items.append({
                            'id': file_id,
                            'name': name,
                            'mimeType': 'application/octet-stream',
                            'size': 0,
                            'isFolder': False  # Will try to detect later
                        })

            # Remove duplicates by ID
            seen_ids = set()
            unique_items = []
            for item in items:
                if item['id'] not in seen_ids:
                    seen_ids.add(item['id'])
                    unique_items.append(item)

            return unique_items

        except Exception as e:
            print(f"⚠️ HTML parsing error: {e}")
            import traceback
            traceback.print_exc()
            return []

    def _fetch_via_batch_api(self, folder_id: str) -> List[Dict]:
        """Fetch using Drive's batch API endpoint"""
        try:
            print("🔄 Trying batch API method...")

            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept': 'application/json',
                'Accept-Language': 'en-US,en;q=0.9',
                'Referer': f'https://drive.google.com/drive/folders/{folder_id}',
                'Content-Type': 'application/json',
                'X-Drive-First-Party': 'DriveWebUi',
            }

            # Add authorization
            auth_header = self._extract_key_from_cookies()
            if auth_header:
                headers['Authorization'] = auth_header

            # Batch API URL
            api_url = 'https://drive.google.com/drive/v2beta/files'

            params = {
                'q': f'"{folder_id}" in parents and trashed=false',
                'fields': 'items(id,title,mimeType,fileSize)',
                'maxResults': 1000,
            }

            response = self.session.get(api_url, params=params, headers=headers, timeout=30)

            if response.status_code == 200:
                data = response.json()
                items = []

                if 'items' in data:
                    for item in data['items']:
                        items.append({
                            'id': item['id'],
                            'name': item.get('title', 'unnamed'),
                            'mimeType': item.get('mimeType', 'application/octet-stream'),
                            'size': int(item.get('fileSize', 0)) if item.get('fileSize') else 0,
                            'isFolder': item.get('mimeType') == 'application/vnd.google-apps.folder'
                        })

                return items

            return []

        except Exception as e:
            print(f"⚠️ Batch API error: {e}")
            return []

    def _download_single_file(self, file_id: str, file_name: str, output_path: Path) -> bool:
        """Download a single file with enhanced error handling"""
        try:
            # Sanitize filename
            safe_name = re.sub(r'[<>:"/\\|?*]', '_', file_name)
            print(f"  📥 Downloading: {safe_name}")

            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept': '*/*',
                'Accept-Language': 'en-US,en;q=0.9',
                'Referer': 'https://drive.google.com/',
            }

            # Initial request
            url = f'https://drive.google.com/uc?export=download&id={file_id}'
            response = self.session.get(url, headers=headers, stream=True, timeout=30, allow_redirects=True)

            # Handle virus scan warning
            content_type = response.headers.get('Content-Type', '').lower()
            if 'text/html' in content_type:
                html_content = response.text

                if 'download-form' in html_content or 'virus' in html_content.lower():
                    form_data = self._parse_download_form(html_content)
                    if form_data:
                        download_url = form_data['action']
                        query_string = urlencode(form_data['params'])
                        full_url = f"{download_url}?{query_string}"
                        response = self.session.get(full_url, headers=headers, stream=True, timeout=30, allow_redirects=True)
                    else:
                        # Try alternative method
                        confirm_match = re.search(r'confirm=([a-zA-Z0-9_-]+)', html_content)
                        uuid_match = re.search(r'uuid=([a-zA-Z0-9_-]+)', html_content)

                        if confirm_match or uuid_match:
                            params = {'id': file_id, 'export': 'download'}
                            if confirm_match:
                                params['confirm'] = confirm_match.group(1)
                            if uuid_match:
                                params['uuid'] = uuid_match.group(1)

                            download_url = f"https://drive.usercontent.google.com/download?{urlencode(params)}"
                            response = self.session.get(download_url, headers=headers, stream=True, timeout=30, allow_redirects=True)

            # Check if we got actual file content
            if response.status_code != 200:
                print(f"  ❌ HTTP {response.status_code}: {safe_name}")
                self.failed_files.append(safe_name)
                return False

            # Save file
            output_file = output_path / safe_name
            total_size = int(response.headers.get('content-length', 0))
            downloaded = 0

            with open(output_file, 'wb') as f:
                for chunk in response.iter_content(chunk_size=32768):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)

            if downloaded > 0:
                self.downloaded_files.append(str(output_file))
                self.total_size += downloaded
                size_mb = downloaded / (1024 * 1024)
                print(f"  ✅ {safe_name} ({size_mb:.2f} MB)")
                return True
            else:
                print(f"  ❌ {safe_name} (0 bytes)")
                self.failed_files.append(safe_name)
                output_file.unlink(missing_ok=True)
                return False

        except Exception as e:
            print(f"  ❌ Error: {file_name} - {e}")
            self.failed_files.append(file_name)
            return False

    def _parse_download_form(self, html_content: str) -> Optional[Dict]:
        """Parse virus scan warning form"""
        try:
            soup = BeautifulSoup(html_content, 'html.parser')
            form = soup.find('form', {'id': 'download-form'})

            if not form:
                return None

            action = form.get('action', '')
            params = {}

            for input_tag in form.find_all('input'):
                name = input_tag.get('name')
                value = input_tag.get('value')
                if name and value:
                    params[name] = value

            return {'action': action, 'params': params}
        except:
            return None

    def download_folder_recursive(self, folder_id: str, output_path: Path,
                                  current_path: str = "", depth: int = 0) -> bool:
        """
        Recursively download all files from a folder

        Args:
            folder_id: Google Drive folder ID
            output_path: Base output directory
            current_path: Current relative path in folder structure
            depth: Current recursion depth (for logging)
        """
        try:
            indent = "  " * depth

            # Create directory for current folder
            current_dir = output_path / current_path if current_path else output_path
            current_dir.mkdir(parents=True, exist_ok=True)

            # Get folder contents
            items = self._get_folder_contents(folder_id)

            if not items:
                print(f"{indent}⚠️ No items found or unable to fetch contents")
                return False

            print(f"{indent}📊 Found {len(items)} items")

            # Separate files and folders
            files = [item for item in items if not item['isFolder']]
            folders = [item for item in items if item['isFolder']]

            print(f"{indent}  📄 Files: {len(files)}")
            print(f"{indent}  📁 Subfolders: {len(folders)}")

            # Download all files in current folder
            if files:
                print(f"{indent}⬇️ Downloading {len(files)} file(s)...")
                for i, file_item in enumerate(files, 1):
                    print(f"{indent}  [{i}/{len(files)}]", end=" ")
                    self._download_single_file(
                        file_item['id'],
                        file_item['name'],
                        current_dir
                    )
                    time.sleep(0.3)  # Rate limiting

            # Recursively process subfolders
            if folders:
                print(f"{indent}📂 Processing {len(folders)} subfolder(s)...")
                for folder_item in folders:
                    print(f"\n{indent}📂 Entering: {folder_item['name']}")
                    subfolder_path = f"{current_path}/{folder_item['name']}" if current_path else folder_item['name']

                    self.download_folder_recursive(
                        folder_item['id'],
                        output_path,
                        subfolder_path,
                        depth + 1
                    )

                    time.sleep(0.5)  # Rate limiting between folders

            return True

        except Exception as e:
            print(f"❌ Error in recursive download: {e}")
            import traceback
            traceback.print_exc()
            return False

    def print_summary(self):
        """Print download summary"""
        print("\n" + "=" * 60)
        print("📊 DOWNLOAD SUMMARY")
        print("=" * 60)
        print(f"✅ Successfully downloaded: {len(self.downloaded_files)} files")
        print(f"❌ Failed: {len(self.failed_files)} files")
        print(f"📦 Total size: {self.total_size / (1024 * 1024):.2f} MB")

        if self.failed_files:
            print("\n❌ Failed files:")
            for failed in self.failed_files[:10]:  # Show first 10
                print(f"  - {failed}")
            if len(self.failed_files) > 10:
                print(f"  ... and {len(self.failed_files) - 10} more")

        print("=" * 60)


def _try_backend_folder_download(self, folder_id: str, output_path: Path) -> bool:
    """
    Enhanced method: Try to download folder via backend API with recursive traversal

    This method:
    1. Uses authenticated session with multiple API fallbacks
    2. Recursively traverses subfolders
    3. Downloads all files maintaining folder structure
    4. Provides progress tracking and error handling
    """
    try:
        print(f"🔗 Attempting recursive folder download...")
        print(f"📂 Folder ID: {folder_id}")
        print(f"📁 Output: {output_path}\n")

        # Validate session first
        if not self._validate_session():
            print("⚠️ Session validation failed - re-authenticating...")
            if not self._authenticate_with_browser():
                print("❌ Authentication failed")
                return False

        # Create folder downloader instance with authenticated session
        downloader = FolderDownloader(self.session)

        # Start recursive download
        success = downloader.download_folder_recursive(folder_id, output_path)

        # Print summary
        downloader.print_summary()

        return success and len(downloader.downloaded_files) > 0

    except Exception as e:
        print(f"❌ Backend folder download failed: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    print("Enhanced Google Drive Folder Downloader v2.0")
    print("=" * 60)
    print("\nFeatures:")
    print("✅ Recursive folder traversal with authenticated session")
    print("✅ Multiple API methods (Query, HTML parsing, Batch)")
    print("✅ Maintains complete folder structure")
    print("✅ Progress tracking with file counts")
    print("✅ Robust error handling")
    print("✅ Download summary with statistics")
    print("=" * 60)