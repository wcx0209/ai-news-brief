from io import BytesIO
from pathlib import Path
import socket
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import source_images as images


def picture(size=(800, 450), kind="PNG"):
    from PIL import Image

    result = BytesIO()
    Image.new("RGB", size, "orange").save(result, format=kind)
    return result.getvalue()


class Response:
    def __init__(self, body=b"", status=200, headers=None):
        self.body = body
        self.status_code = status
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def iter_content(self, chunk_size):
        for position in range(0, len(self.body), chunk_size):
            yield self.body[position:position + chunk_size]


class SourceImageTests(unittest.TestCase):
    def test_relative_lazy_srcset_and_signed_queries_stay_intact(self):
        html = '''<article><picture><source srcset="/small.jpg 320w, //cdn.example.org/full.jpg?rect=0,0,100,100&amp;s=KEEP 1600w">
          <img src="/placeholder.png" data-src="../lazy.jpg" data-original="/original.jpg"></picture></article>'''
        result = images.extract_candidates(html, "https://publisher.example.org/blog/post")
        self.assertEqual(result[0], "https://cdn.example.org/full.jpg?rect=0,0,100,100&s=KEEP")
        self.assertIn("https://publisher.example.org/lazy.jpg", result)
        self.assertLess(result.index("https://publisher.example.org/original.jpg"), result.index("https://publisher.example.org/placeholder.png"))

    def test_metadata_main_jsonld_only_and_navigation_excluded(self):
        html = '''<meta property="og:image" content="/og.jpg"><meta property="og:image:secure_url" content="//cdn.example.org/secure.jpg">
          <meta name="twitter:image" content="/twitter.jpg">
          <script type="application/ld+json">{"@graph":[{"@type":"Organization","image":"/brand.jpg"},
            {"@type":"NewsArticle","image":{"@type":"ImageObject","contentUrl":"/main.jpg"}}]}</script>
          <nav><img src="/outside-nav.jpg"></nav><main><nav><img src="/inside-nav.jpg"></nav>
          <article><img data-src="/body.jpg"></article></main>'''
        result = images.extract_candidates(html, "https://publisher.example.org/news/")
        self.assertEqual(result[:3], ["https://cdn.example.org/secure.jpg", "https://publisher.example.org/og.jpg", "https://publisher.example.org/twitter.jpg"])
        self.assertIn("https://publisher.example.org/main.jpg", result)
        self.assertIn("https://publisher.example.org/body.jpg", result)
        self.assertFalse(any("nav.jpg" in url or "brand.jpg" in url for url in result))
        self.assertEqual(len(result), len(set(result)))

    def test_low_resolution_og_falls_through_to_valid_body_image(self):
        html = b'<meta property="og:image" content="/low.png"><article><img src="/valid.png"></article>'
        with patch.object(images, "_fetch_bytes", side_effect=[
            ("https://publisher.example.org/redirected/news/", html, "text/html"),
            ("https://publisher.example.org/low.png", picture((320, 200)), "image/png"),
            ("https://publisher.example.org/valid.png", picture(), "image/png"),
        ]) as fetch:
            result = images.discover_images("https://publisher.example.org/old", limit=1)
        self.assertEqual(result, ["https://publisher.example.org/valid.png"])
        self.assertEqual(fetch.call_args_list[1].args[0], "https://publisher.example.org/low.png")
        self.assertTrue(fetch.call_args_list[1].kwargs["image"])

    def test_div_only_body_lazy_srcset_follows_low_resolution_og(self):
        html = b'''<meta property="og:image" content="/low-logo.png">
          <div class="article-content"><img src="/placeholder.gif" data-src="/lazy.jpg"
          data-original="/original.jpg" data-srcset="/small.jpg 320w, /full.jpg?sig=KEEP 1600w"></div>'''
        with patch.object(images, "_fetch_bytes", side_effect=[
            ("https://publisher.example.org/story", html, "text/html"),
            ("https://publisher.example.org/low-logo.png", picture((320, 100)), "image/png"),
            ("https://publisher.example.org/full.jpg?sig=KEEP", picture(), "image/jpeg"),
        ]) as fetch:
            result = images.discover_images("https://publisher.example.org/story", limit=1)
        self.assertEqual(result, ["https://publisher.example.org/full.jpg?sig=KEEP"])
        self.assertEqual(fetch.call_args_list[2].args[0], "https://publisher.example.org/full.jpg?sig=KEEP")

    def test_explicit_div_body_containers_covered_without_full_page_images(self):
        for classes in ("article-content", "post-content", "entry-content", "article-body", "post-body"):
            html = f'''<img src="/unmarked.jpg"><nav><div class="{classes}"><img src="/nav.jpg"></div></nav>
              <header><div class="{classes}"><img src="/header.jpg"></div></header>
              <footer><div class="{classes}"><img src="/footer.jpg"></div></footer>
              <div class="{classes}"><img data-original="/body.jpg"></div>'''
            with self.subTest(classes=classes):
                self.assertEqual(images.extract_candidates(html, "https://publisher.example.org/story"),
                                 ["https://publisher.example.org/body.jpg"])
        self.assertEqual(images.extract_candidates('<div itemprop="articleBody"><img data-src="/schema.jpg"></div>',
                                                   "https://publisher.example.org/story"),
                         ["https://publisher.example.org/schema.jpg"])

    def test_redirected_page_is_base_for_relative_image(self):
        with patch.object(images, "_fetch_bytes", side_effect=[
            ("https://new.example.org/path/post/", b'<article><img src="../figure.png"></article>', "text/html"),
            ("https://new.example.org/path/figure.png", picture(), "image/png"),
        ]):
            self.assertEqual(images.discover_images("https://publisher.example.org/old"), ["https://new.example.org/path/figure.png"])

    def test_corrupt_truncated_lowres_and_pixel_bomb_rejected(self):
        self.assertFalse(images._complete_image(b"not an image"))
        self.assertFalse(images._complete_image(picture(kind="JPEG")[:-30]))
        self.assertFalse(images._complete_image(picture((479, 600))))
        self.assertFalse(images._complete_image(picture((800, 269))))
        self.assertTrue(images._complete_image(picture((480, 270))))
        self.assertTrue(images._complete_image(picture((480, 360), "GIF")))
        self.assertFalse(images._complete_image(picture((480, 360), "GIF")[:-1]))
        with patch.object(images, "MAX_PIXELS", 100_000):
            self.assertFalse(images._complete_image(picture()))

    def test_animation_all_frames_decode_with_bounded_work(self):
        from PIL import Image

        output = BytesIO()
        first, second = Image.new("RGB", (480, 270), "orange"), Image.new("RGB", (480, 270), "black")
        first.save(output, format="GIF", save_all=True, append_images=[second])
        body = output.getvalue()
        self.assertTrue(images._complete_image(body))
        with patch.object(images, "MAX_FRAMES", 1):
            self.assertFalse(images._complete_image(body))
        with patch.object(images, "MAX_DECODE_PIXELS", 480 * 270):
            self.assertFalse(images._complete_image(body))

    def test_unsafe_urls_are_rejected_without_fetch(self):
        unsafe = ["file:///etc/passwd", "http://localhost/a", "http://127.0.0.1/a", "http://169.254.169.254/a",
                  "http://[::1]/a", "http://[fc00::1]/a", "http://[::ffff:127.0.0.1]/a", "https://user:pass@example.org/a",
                  "https://example.org:8080/a", "https://example.org/\r\na", "https://example.org\\@127.0.0.1/a"]
        for url in unsafe:
            with self.subTest(url=url), patch.object(images, "_fetch_bytes") as fetch:
                self.assertIsNone(images.normalize_source_url(url))
                self.assertEqual(images.discover_images(url), [])
                fetch.assert_not_called()

    def test_normalization_does_not_rewrite_signed_queries(self):
        self.assertEqual(images.normalize_source_url("HTTPS://CDN.EXAMPLE.ORG:443/p.jpg?s=ABC&rect=0%2C1%2C2%2C3#old"),
                         "https://cdn.example.org/p.jpg?s=ABC&rect=0%2C1%2C2%2C3")

    def test_dns_all_addresses_must_be_public(self):
        answers = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443)),
                   (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("::1", 443, 0, 0))]
        with patch.object(images.socket, "getaddrinfo", return_value=answers), patch.object(images, "_request_once") as fetch:
            self.assertIsNone(images._fetch_bytes("https://publisher.example.org/", 100, 1))
            fetch.assert_not_called()

    def test_multicast_and_ipv4_transition_private_targets_are_not_public(self):
        for address in ("224.0.0.1", "ff02::1", "64:ff9b::7f00:1", "2002:7f00:1::", "fec0::1"):
            with self.subTest(address=address):
                self.assertFalse(images._public_ip(address))
        self.assertTrue(images._public_ip("8.8.8.8"))
        self.assertTrue(images._public_ip("2001:4860:4860::8888"))

    def test_public_address_is_pinned_with_original_tls_hostname(self):
        adapter = images._pinned_adapter("publisher.example.org", "8.8.8.8", 443)
        pool = adapter.get_connection("https://publisher.example.org/article")
        self.assertEqual(pool.host, "8.8.8.8")
        self.assertEqual(pool.assert_hostname, "publisher.example.org")
        self.assertEqual(pool.conn_kw["server_hostname"], "publisher.example.org")
        adapter.close()

    def test_redirect_private_destination_is_not_requested(self):
        first = Response(status=302, headers={"Location": "http://127.0.0.1/secret"})
        with patch.object(images, "_resolve_public", return_value=["8.8.8.8"]), patch.object(images, "_request_once", return_value=first) as fetch:
            self.assertIsNone(images._fetch_bytes("https://publisher.example.org/", 100, 1))
            self.assertEqual(fetch.call_count, 1)

    def test_redirect_dns_is_revalidated_and_hops_bounded(self):
        first = Response(status=302, headers={"Location": "https://cdn.example.org/image"})
        with patch.object(images, "_resolve_public", side_effect=[["8.8.8.8"], ValueError("private")]) as resolve, patch.object(images, "_request_once", return_value=first) as fetch:
            self.assertIsNone(images._fetch_bytes("https://publisher.example.org/", 100, 1))
            self.assertEqual(resolve.call_count, 2)
            self.assertEqual(fetch.call_count, 1)
        with patch.object(images, "_resolve_public", return_value=["8.8.8.8"]), patch.object(images, "_request_once", return_value=first) as fetch:
            self.assertIsNone(images._fetch_bytes("https://publisher.example.org/", 100, 1))
            self.assertEqual(fetch.call_count, 4)

    def test_stream_and_declared_byte_limits_and_html_masquerading(self):
        for response in (Response(b"x" * 33), Response(b"ok", headers={"Content-Length": "33"}),
                         Response(b"<html>blocked</html>", headers={"Content-Type": "text/html"})):
            with patch.object(images, "_resolve_public", return_value=["8.8.8.8"]), patch.object(images, "_request_once", return_value=response):
                self.assertIsNone(images._fetch_bytes("https://cdn.example.org/a", 32, 1, image=True))

    def test_attempts_limited_to_six_and_result_to_three(self):
        html = ("<article>" + "".join(f'<img src="/{index}.png">' for index in range(20)) + "</article>").encode()
        with patch.object(images, "_fetch_bytes", side_effect=[("https://publisher.example.org/", html, "text/html")] + [None] * 6) as fetch:
            self.assertEqual(images.discover_images("https://publisher.example.org/"), [])
            self.assertEqual(fetch.call_count, 7)
        with patch.object(images, "_fetch_bytes", side_effect=[("https://publisher.example.org/", html, "text/html")] +
                          [(f"https://cdn.example.org/{index}.png", picture(), "image/png") for index in range(3)]) as fetch:
            self.assertEqual(len(images.discover_images("https://publisher.example.org/", limit=100)), 3)
            self.assertEqual(fetch.call_count, 4)

    def test_youtube_thumbnail_is_verified_not_blindly_returned(self):
        with patch.object(images, "_fetch_bytes", side_effect=[
            ("https://i.ytimg.com/vi/abcdefghijk/maxresdefault.jpg", picture((120, 90)), "image/jpeg"),
            ("https://i.ytimg.com/vi/abcdefghijk/hqdefault.jpg", picture((480, 360)), "image/jpeg"),
        ]) as fetch:
            self.assertEqual(images.discover_images("https://www.youtube.com/watch?v=abcdefghijk"),
                             ["https://i.ytimg.com/vi/abcdefghijk/hqdefault.jpg"])
            self.assertEqual(fetch.call_count, 2)
            self.assertTrue(all(call.kwargs.get("image") for call in fetch.call_args_list))
        self.assertEqual(images._youtube_images("https://notyoutube.com/watch?v=abcdefghijk"), [])

    def test_zero_limit_does_not_fetch(self):
        with patch.object(images, "_fetch_bytes") as fetch:
            self.assertEqual(images.discover_images("https://publisher.example.org/", limit=0), [])
            fetch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
