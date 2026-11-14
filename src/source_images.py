"""Bounded discovery of complete source images, without a public proxy/cache.

Candidates keep their publisher URL (including signed query parameters). Network
requests are anonymous, DNS-pinned to public addresses and checked at every hop.
No image is returned until its bytes and decoded dimensions have been checked.
"""

from contextlib import contextmanager
from io import BytesIO
import ipaddress
import json
import math
import re
import socket
import time
from urllib.parse import parse_qs, urljoin, urlsplit, urlunsplit
import warnings

HTML_BYTES = 1024 * 1024
IMAGE_BYTES = 5 * 1024 * 1024
MAX_PIXELS = 40_000_000
MAX_DECODE_PIXELS = 160_000_000
MAX_FRAMES = 512
MAX_REDIRECTS = 3
MAX_ATTEMPTS = 6
USER_AGENT = "Polyemergence/1.0 (+https://polyemergence.com)"
ARTICLE_TYPES = frozenset({"article", "newsarticle", "blogposting"})
REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
BODY_SELECTOR = (
    "article, main, div.article-content, div.post-content, div.entry-content, "
    "div.article-body, div.post-body, [itemprop='articleBody']"
)


def _public_ip(value):
    try:
        address = ipaddress.ip_address(value)
        mapped = getattr(address, "ipv4_mapped", None)
        if (not address.is_global or address.is_multicast or address.is_reserved or
                address.is_loopback or address.is_link_local or address.is_unspecified or
                getattr(address, "is_site_local", False)):
            return False
        if isinstance(address, ipaddress.IPv6Address):
            # Do not allow a translation/tunnel address to hide a private IPv4
            # target from the ordinary public-address checks.
            if address in ipaddress.ip_network("64:ff9b::/96") or address in ipaddress.ip_network("64:ff9b:1::/48"):
                return False
            if address.sixtofour is not None and not _public_ip(str(address.sixtofour)):
                return False
            if address.teredo is not None and not all(_public_ip(str(part)) for part in address.teredo):
                return False
        return mapped is None or _public_ip(str(mapped))
    except ValueError:
        return False


def normalize_source_url(value):
    """Syntax-only URL guard for source binding; does not perform DNS/network.

    Public DNS validation belongs to the fetch path below. This function must
    not be used alone to authorize an outbound request. Paths/queries are not
    decoded, resized, unsigned, or otherwise rewritten.
    """
    if not isinstance(value, str) or not value or len(value) > 8192:
        return None
    if "\\" in value or any(ord(char) <= 32 or 127 <= ord(char) <= 159 for char in value):
        return None
    try:
        parsed = urlsplit(value)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
            return None
        if parsed.username is not None or parsed.password is not None:
            return None
        port = parsed.port
        if port not in {None, 80, 443}:
            return None
        host = parsed.hostname.lower().rstrip(".")
        if "%" in host:
            return None
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            host = host.encode("idna").decode("ascii")
            if ("." not in host or len(host) > 253 or
                    any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
                        for label in host.split(".")) or
                    host.endswith((".localhost", ".local", ".internal", ".home.arpa"))):
                return None
        else:
            if not _public_ip(str(address)):
                return None
            host = f"[{address.compressed}]" if address.version == 6 else str(address)
        scheme = parsed.scheme.lower()
        if port is not None and port != (443 if scheme == "https" else 80):
            host += f":{port}"
        return urlunsplit((scheme, host, parsed.path or "/", parsed.query, ""))
    except (ValueError, UnicodeError):
        return None


def _candidate_url(value, page_url):
    if not isinstance(value, str) or not value:
        return None
    if "\\" in value or any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in value):
        return None
    value = value.strip()
    if value.startswith("//"):
        value = "https:" + value
    return normalize_source_url(urljoin(page_url, value))


def _srcset(value):
    """Read URL tokens without splitting commas inside signed image queries."""
    candidates, position = [], 0
    value = str(value or "")
    while position < len(value):
        while position < len(value) and (value[position].isspace() or value[position] == ","):
            position += 1
        match = re.match(r"\S+", value[position:])
        if not match:
            break
        url = match.group()
        position += len(url)
        descriptor = ""
        if url.endswith(","):
            url = url.rstrip(",")
        else:
            end = value.find(",", position)
            if end < 0:
                end = len(value)
            descriptor = value[position:end].strip()
            position = end + 1
        size = re.fullmatch(r"(\d+(?:\.\d+)?)(w|x)", descriptor)
        rank = float(size[1]) * (1000 if size[2] == "x" else 1) if size else 0
        if url:
            candidates.append((rank, url))
    return [url for _, url in sorted(candidates, key=lambda item: -item[0])]


def _article_images(value):
    if isinstance(value, list):
        for child in value:
            yield from _article_images(child)
    elif isinstance(value, dict):
        types = value.get("@type", [])
        types = types if isinstance(types, list) else [types]
        if any(str(kind).rstrip("/").rsplit("/", 1)[-1].lower() in ARTICLE_TYPES for kind in types):
            images = value.get("image", [])
            images = images if isinstance(images, list) else [images]
            for image in images:
                if isinstance(image, str):
                    yield image
                elif isinstance(image, dict):
                    for key in ("contentUrl", "url"):
                        if isinstance(image.get(key), str):
                            yield image[key]
        for key in ("@graph", "mainEntity"):
            if key in value:
                yield from _article_images(value[key])


def extract_candidates(html, page_url, limit=12):
    """Pure parsing: metadata then explicitly marked article bodies, not page UI."""
    from bs4 import BeautifulSoup

    page_url = normalize_source_url(page_url)
    if not page_url:
        return []
    try:
        limit = min(12, max(0, int(limit)))
    except (TypeError, ValueError, OverflowError):
        return []
    if not limit:
        return []
    soup = BeautifulSoup(html[:HTML_BYTES], "html.parser")
    host = urlsplit(page_url).hostname or ""
    qbit_body = host == "qbitai.com" or host.endswith(".qbitai.com")
    raw = []
    metas = soup.find_all("meta")
    for names in (("og:image:secure_url",), ("og:image", "og:image:url"), ("twitter:image", "twitter:image:src")):
        raw.extend(node.get("content") for node in metas
                   if str(node.get("property") or node.get("name") or "").lower() in names)
    for node in soup.find_all("script", attrs={"type": re.compile(r"^application/ld\+json$", re.I)}):
        try:
            raw.extend(_article_images(json.loads(node.string or node.get_text())))
        except (ValueError, TypeError, RecursionError):
            continue
    # Some publisher templates use div-based WordPress/editor body containers
    # rather than semantic article/main elements. Do not fall back to all imgs:
    # navigation, site chrome, and unmarked recommendation blocks stay outside.
    # QbitAI's inspected publisher template uses div.article for the body,
    # unlike the generic div.article cards used on many unrelated sites.
    selector = BODY_SELECTOR + (", div.article" if qbit_body else "")
    for root in soup.select(selector):
        for node in root.find_all("img"):
            if any(parent.name in {"nav", "header", "footer"} or parent.get("role") in {"navigation", "banner"}
                   or (qbit_body and "article_info" in (parent.get("class") or []))
                   for parent in node.parents if getattr(parent, "attrs", None) is not None):
                continue
            picture = node.find_parent("picture")
            if picture:
                for source in picture.find_all("source"):
                    raw.extend(_srcset(source.get("data-srcset") or source.get("srcset")))
            raw.extend(_srcset(node.get("data-srcset") or node.get("srcset")))
            raw.extend(node.get(key) for key in ("data-original", "data-src", "src"))
    result, seen = [], set()
    for value in raw:
        url = _candidate_url(value, page_url)
        if url and url not in seen:
            result.append(url)
            seen.add(url)
            if len(result) >= limit:
                break
    return result


def _resolve_public(url):
    parsed = urlsplit(url)
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    addresses = {answer[4][0] for answer in socket.getaddrinfo(parsed.hostname, port, type=socket.SOCK_STREAM)}
    if not addresses or not all(_public_ip(address) for address in addresses):
        raise ValueError("Image/source host must resolve only to public addresses")
    # Pin the validated address for the actual connection, not a second DNS
    # lookup that could be rebound to a private address between validation/use.
    return sorted(addresses, key=lambda address: (":" in address, address))


def _pinned_adapter(host, address, port):
    from requests.adapters import HTTPAdapter

    class PinnedAdapter(HTTPAdapter):
        def _pool(self, url):
            scheme = urlsplit(url).scheme
            options = {"assert_hostname": host, "server_hostname": host} if scheme == "https" else {}
            return self.poolmanager.connection_from_host(address, port, scheme, pool_kwargs=options)

        def get_connection(self, url, proxies=None):
            return self._pool(url)

        def get_connection_with_tls_context(self, request, verify, proxies=None, cert=None):
            return self._pool(request.url)

    return PinnedAdapter(max_retries=0)


@contextmanager
def _request_once(url, addresses, timeout):
    import requests

    parsed = urlsplit(url)
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    with requests.Session() as session:
        session.trust_env = False  # No environment proxy, .netrc auth or cookies.
        session.mount(parsed.scheme + "://", _pinned_adapter(parsed.hostname, addresses[0], port))
        headers = {"User-Agent": USER_AGENT, "Accept": "image/*,text/html;q=0.8,*/*;q=0.1", "Host": parsed.netloc}
        with session.get(url, headers=headers, timeout=timeout, stream=True, allow_redirects=False) as response:
            yield response


def _fetch_bytes(url, maximum, timeout, image=False):
    import requests

    current = normalize_source_url(url)
    if not current:
        return None
    try:
        seconds = float(timeout)
        seconds = min(30, max(.1, seconds)) if math.isfinite(seconds) else 8
        deadline = time.monotonic() + seconds
        for redirects in range(MAX_REDIRECTS + 1):
            addresses = _resolve_public(current)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            with _request_once(current, addresses, (min(3, remaining), remaining)) as response:
                if response.status_code in REDIRECT_STATUSES:
                    if redirects == MAX_REDIRECTS:
                        return None
                    destination = _candidate_url(response.headers.get("Location"), current)
                    if not destination:
                        return None
                    current = destination
                    continue
                if response.status_code != 200:
                    return None
                content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
                if image:
                    if content_type and not content_type.startswith("image/") and content_type != "application/octet-stream":
                        return None
                elif content_type and content_type not in {"text/html", "application/xhtml+xml"}:
                    return None
                length = response.headers.get("Content-Length", "")
                if str(length).isdigit() and int(length) > maximum:
                    return None
                parts, size = [], 0
                for part in response.iter_content(chunk_size=16384):
                    size += len(part)
                    if size > maximum or time.monotonic() > deadline:
                        return None
                    parts.append(part)
                return current, b"".join(parts), content_type
    except (requests.RequestException, OSError, ValueError, OverflowError):
        return None
    return None


def _image_status(body):
    from PIL import Image

    if not body or len(body) > IMAGE_BYTES:
        return "unavailable"
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(body)) as image:
                width, height = image.size
                low_resolution = width < 480 or height < 270
                if width * height > MAX_PIXELS:
                    return "unavailable"
                if image.format == "GIF" and not body.rstrip().endswith(b";"):
                    return "unavailable"
                image.verify()
            # verify() checks structure; load() forces a fresh full pixel decode
            # so a JPEG header alone or a truncated raster is not accepted.
            with Image.open(BytesIO(body)) as image:
                decoded_pixels = frames = 0
                while True:
                    width, height = image.size
                    frames += 1
                    decoded_pixels += width * height
                    if width * height > MAX_PIXELS or decoded_pixels > MAX_DECODE_PIXELS or frames > MAX_FRAMES:
                        return "unavailable"
                    image.load()
                    try:
                        image.seek(image.tell() + 1)
                    except EOFError:
                        break
        return "low_resolution" if low_resolution else "verified"
    except Exception:
        # Decoders may raise format-specific errors for malformed third-party
        # bytes. A corrupt image must fail closed, not abort the news export.
        return "unavailable"


def _complete_image(body):
    return _image_status(body) == "verified"


def _report_low_resolution(rejected, candidate, final_url):
    if not isinstance(rejected, list):
        return
    for value in (candidate, final_url):
        safe = normalize_source_url(value)
        if safe and safe not in rejected and len(rejected) < 12:
            rejected.append(safe)


def _youtube_images(url):
    parsed = urlsplit(url)
    host, identifier = parsed.hostname or "", None
    if host == "youtu.be":
        identifier = parsed.path.strip("/").split("/")[0]
    elif host == "youtube.com" or host.endswith(".youtube.com"):
        if parsed.path == "/watch":
            identifier = parse_qs(parsed.query).get("v", [None])[0]
        elif parsed.path.startswith(("/shorts/", "/embed/", "/live/")):
            identifier = parsed.path.strip("/").split("/")[1]
    if identifier and re.fullmatch(r"[A-Za-z0-9_-]{11}", identifier):
        return [f"https://i.ytimg.com/vi/{identifier}/{name}.jpg" for name in ("maxresdefault", "hqdefault")]
    return []


def discover_images(article_url, timeout=8, limit=3, rejected=None):
    """Return up to three safely fetched, decoded, sufficiently large images.

    At most six candidate image URLs are attempted; three redirects per request
    are allowed. A failed/blocked original is skipped, never proxied to readers.
    If supplied, ``rejected`` receives up to 12 safely formatted original/final
    URLs confirmed low-resolution after a successful complete raster decode.
    Temporary failures and resource limits are not evidence of low resolution.
    """
    article_url = normalize_source_url(article_url)
    try:
        limit = min(3, max(0, int(limit)))
    except (TypeError, ValueError, OverflowError):
        return []
    if not article_url or not limit:
        return []
    candidates = _youtube_images(article_url)
    if not candidates:
        fetched = _fetch_bytes(article_url, HTML_BYTES, timeout)
        if not fetched:
            return []
        page_url, body, _ = fetched
        candidates = extract_candidates(body, page_url)
    verified = []
    for candidate in candidates[:MAX_ATTEMPTS]:
        fetched = _fetch_bytes(candidate, IMAGE_BYTES, timeout, image=True)
        status = _image_status(fetched[1]) if fetched else "unavailable"
        if status == "low_resolution":
            _report_low_resolution(rejected, candidate, fetched[0])
        elif status == "verified":
            final_url = fetched[0]
            if final_url not in verified:
                verified.append(final_url)
            if len(verified) >= limit:
                break
    return verified
