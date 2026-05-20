import unittest
from unittest.mock import patch, MagicMock
import os
import shutil
import tempfile
from bs4 import BeautifulSoup

# Import the functions under test
import scraper

class TestScraper(unittest.TestCase):
    def setUp(self):
        # Reset crawler state
        scraper.crawled_pages = set()
        scraper.downloaded_assets = {}
        scraper.output_dir = "/output"
        scraper.target_domain = "fan60.princeton.edu"
        scraper.allowed_asset_domains = ["fan60.princeton.edu", "*.princeton.edu"]
        scraper.headers = {}

    def test_clean_url(self):
        self.assertEqual(scraper.clean_url("https://example.com/page#anchor"), "https://example.com/page")
        self.assertEqual(scraper.clean_url("https://example.com/page?query=123"), "https://example.com/page?query=123")
        self.assertEqual(scraper.clean_url("https://example.com/"), "https://example.com/")

    def test_is_asset_url(self):
        # Verify asset extensions return True
        self.assertTrue(scraper.is_asset_url("https://example.com/style.css"))
        self.assertTrue(scraper.is_asset_url("https://example.com/image.png"))
        self.assertTrue(scraper.is_asset_url("https://example.com/font.woff2"))
        
        # Verify non-assets return False
        self.assertFalse(scraper.is_asset_url("https://example.com/invited-speakers"))
        self.assertFalse(scraper.is_asset_url("https://example.com/about/"))

    def test_domain_matches(self):
        # Asset allowed domain checks (*.princeton.edu)
        self.assertTrue(scraper.domain_matches("fan60.princeton.edu", ["fan60.princeton.edu", "*.princeton.edu"]))
        self.assertTrue(scraper.domain_matches("orfe.princeton.edu", ["fan60.princeton.edu", "*.princeton.edu"]))
        
        # Non-allowed domains
        self.assertFalse(scraper.domain_matches("google.com", ["fan60.princeton.edu", "*.princeton.edu"]))

    def test_url_to_local_path(self):
        # Test webpage path mapping
        self.assertEqual(
            scraper.url_to_local_path("https://fan60.princeton.edu/invited-speakers", is_page=True),
            "invited-speakers/index.html"
        )
        self.assertEqual(
            scraper.url_to_local_path("https://fan60.princeton.edu/", is_page=True),
            "index.html"
        )
        
        # Test asset path mapping
        self.assertEqual(
            scraper.url_to_local_path("https://fan60.princeton.edu/themes/custom/main.css", is_page=False),
            "themes/custom/main.css"
        )
        
        # Test external asset path mapping (gets prefixed with _assets)
        self.assertEqual(
            scraper.url_to_local_path("https://orfe.princeton.edu/images/logo.png", is_page=False),
            "_assets/orfe.princeton.edu/images/logo.png"
        )
        
        # Test percent-encoded path mapping (unquotes path)
        self.assertEqual(
            scraper.url_to_local_path("https://orfe.princeton.edu/images/logo%20with%20spaces@2x.png", is_page=False),
            "_assets/orfe.princeton.edu/images/logo with spaces@2x.png"
        )

    @patch('scraper.session.get')
    def test_download_asset_mock(self, mock_get):
        # Set up a temporary output directory
        temp_dir = tempfile.mkdtemp()
        scraper.output_dir = temp_dir
        
        try:
            # Mock successful asset response
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.content = b"fake binary content"
            mock_resp.iter_content.return_value = [b"fake binary content"]
            mock_get.return_value = mock_resp
            
            asset_url = "https://fan60.princeton.edu/logo.png"
            local_path = scraper.download_asset(asset_url)
            
            # Verify file creation
            expected_file = os.path.join(temp_dir, "logo.png")
            self.assertTrue(os.path.exists(expected_file))
            with open(expected_file, 'rb') as f:
                self.assertEqual(f.read(), b"fake binary content")
                
            self.assertEqual(local_path, "logo.png")
        finally:
            shutil.rmtree(temp_dir)

    @patch('scraper.session.get')
    @patch('scraper.download_asset')
    def test_crawl_page(self, mock_download, mock_get):
        # Mock asset download paths
        mock_download.side_effect = lambda u: "css/style.css" if "style.css" in u else "images/logo.png"

        # Mock HTML page response
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {'Content-Type': 'text/html'}
        mock_resp.text = """
        <html>
            <head>
                <link rel="stylesheet" href="https://fan60.princeton.edu/css/style.css">
            </head>
            <body>
                <a href="https://fan60.princeton.edu/schedule">Schedule</a>
                <img src="https://fan60.princeton.edu/images/logo.png">
            </body>
        </html>
        """
        mock_get.return_value = mock_resp

        temp_dir = tempfile.mkdtemp()
        scraper.output_dir = temp_dir

        try:
            # Crawl a page located at https://fan60.princeton.edu/invited-speakers
            scraper.crawl_page("https://fan60.princeton.edu/invited-speakers")

            # Check that the page was saved to the correct relative path
            expected_html_file = os.path.join(temp_dir, "invited-speakers/index.html")
            self.assertTrue(os.path.exists(expected_html_file))

            with open(expected_html_file, 'r', encoding='utf-8') as f:
                soup = BeautifulSoup(f.read(), 'html.parser')

            # Verify that stylesheet links and image paths were rewritten relative to /invited-speakers
            self.assertEqual(soup.find('link')['href'], "../css/style.css")
            self.assertEqual(soup.find('img')['src'], "../images/logo.png")
            # Verify that the internal page links were rewritten relative to /invited-speakers
            self.assertEqual(soup.find('a')['href'], "../schedule/index.html")

        finally:
            shutil.rmtree(temp_dir)

    @patch('scraper.session.get')
    def test_crawl_page_with_pager_and_login(self, mock_get):
        main_html = """
        <html>
            <body>
                <div class="utility-menu">
                    <ul class="nav navbar-nav utility-nav">
                        <li class="nav-item">
                            <a class="ps-login-link ps-login-logout-link" data-drupal-link-system-path="caslogin" href="caslogin/index.html">Log in</a>
                        </li>
                    </ul>
                </div>
                <div class="block-ps-event-speaker-list">
                    <div class="content-list-items" role="list">
                        <div class="content-list-item">Speaker A</div>
                    </div>
                    <nav class="pager">
                        <ul>
                            <li><a href="https://fan60.princeton.edu/invited-speakers?page=0">1</a></li>
                            <li><a href="https://fan60.princeton.edu/invited-speakers?page=1">2</a></li>
                        </ul>
                    </nav>
                </div>
            </body>
        </html>
        """
        
        page1_html = """
        <html>
            <body>
                <div class="block-ps-event-speaker-list">
                    <div class="content-list-items" role="list">
                        <div class="content-list-item">Speaker B</div>
                    </div>
                </div>
            </body>
        </html>
        """
        
        mock_resp_main = MagicMock()
        mock_resp_main.status_code = 200
        mock_resp_main.headers = {'Content-Type': 'text/html'}
        mock_resp_main.text = main_html
        
        mock_resp_page1 = MagicMock()
        mock_resp_page1.status_code = 200
        mock_resp_page1.headers = {'Content-Type': 'text/html'}
        mock_resp_page1.text = page1_html
        
        def get_side_effect(url, **kwargs):
            if 'page=1' in url:
                return mock_resp_page1
            return mock_resp_main
            
        mock_get.side_effect = get_side_effect
        
        temp_dir = tempfile.mkdtemp()
        scraper.output_dir = temp_dir
        
        try:
            scraper.crawl_page("https://fan60.princeton.edu/invited-speakers")
            
            expected_html_file = os.path.join(temp_dir, "invited-speakers/index.html")
            self.assertTrue(os.path.exists(expected_html_file))
            
            with open(expected_html_file, 'r', encoding='utf-8') as f:
                soup = BeautifulSoup(f.read(), 'html.parser')
                
            self.assertIsNone(soup.find(class_='utility-menu'))
            self.assertIsNone(soup.find('a', class_='ps-login-link'))
            self.assertIsNone(soup.find('nav', class_='pager'))
            
            list_items = soup.find(class_='content-list-items')
            self.assertIsNotNone(list_items)
            items = list_items.find_all(class_='content-list-item')
            self.assertEqual(len(items), 2)
            self.assertEqual(items[0].get_text().strip(), "Speaker A")
            self.assertEqual(items[1].get_text().strip(), "Speaker B")
            
        finally:
            shutil.rmtree(temp_dir)

if __name__ == '__main__':
    unittest.main()

