"""Weekly discovery stays in the shared navigation and out of the news grid."""

import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from html.parser import HTMLParser


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import export_archive as archive

spec = importlib.util.spec_from_file_location("weekly_nav_domain_pages", ROOT / "scripts/export_domain_pages.py")
pages = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pages)


class PrimaryLinks(HTMLParser):
    def __init__(self, page):
        super().__init__()
        self.in_primary = False
        self.links = []
        self.feed(page)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "nav" and "desktop-nav" in attrs.get("class", "").split():
            self.in_primary = True
        elif tag == "a" and self.in_primary:
            self.links.append(attrs.get("href"))

    def handle_endtag(self, tag):
        if tag == "nav":
            self.in_primary = False


class WeeklyNavigationTests(unittest.TestCase):
    def assert_weekly_navigation(self, page, locale, local_hashes=False):
        prefix = "" if local_hashes else f"/{locale}/"
        self.assertEqual(PrimaryLinks(page).links, [
            prefix + "#fields", f"/{locale}/weekly/", f"/{locale}/archive/",
            prefix + "#about", prefix + "#feedback",
        ])
        footer = re.search(r"<footer\b.*?</footer>", page, re.S)[0]
        self.assertIn(f'href="/{locale}/weekly/"', footer)
        self.assertIn("Weekly" if locale == "en" else "周报", footer)

    def test_home_entry_is_static_bilingual_and_remains_field_first(self):
        source = (ROOT / "web/public/app.js").read_text()
        self.assertIn('navWeekly: "Weekly"', source)
        self.assertIn('navWeekly: "周报"', source)
        for locale in ("en", "zh"):
            page = (ROOT / f"web/public/{locale}/index.html").read_text()
            self.assert_weekly_navigation(page, locale, local_hashes=True)
            self.assertRegex(page, r'<section\b[^>]*id="brief"[^>]*\bhidden')
            self.assertIn('id="field-grid"', page)
            self.assertIn(f'href="/{locale}/weekly/" data-weekly-link data-copy="navWeekly"', page)
            self.assertNotIn('id="weekly-story-grid"', page)

    def test_archive_shell_has_locale_weekly_entry_without_changing_selection(self):
        for locale, alternate in (("en", "zh"), ("zh", "en")):
            page = archive.page_shell(locale, "Archive", "A fixture", f"{archive.SITE}/{locale}/archive/",
                                      f"{archive.SITE}/{alternate}/archive/", "<p>Retained fixture</p>")
            self.assert_weekly_navigation(page, locale)
            self.assertIn("<p>Retained fixture</p>", page)
            self.assertIn(f'href="/{locale}/archive/" aria-current="page"', page)

    def test_reexports_keep_weekly_links_and_do_not_replace_weekly_sitemap(self):
        with tempfile.TemporaryDirectory() as directory:
            public = Path(directory)
            for locale in ("en", "zh"):
                (public / locale).mkdir()
                # Wrong-locale weekly links must be normalised by the exporter.
                shell = (ROOT / f"web/public/{locale}/index.html").read_text()
                shell = shell.replace(f'href="/{locale}/weekly/"', 'href="/wrong/weekly/"')
                (public / locale / "index.html").write_text(shell)
            registry = public / "registry.json"
            registry.write_text(json.dumps({"domains": [{"id": "ai", "label": {"en": "AI", "zh": "人工智能"}, "description": {"en": "AI coverage", "zh": "人工智能报道"}}]}))
            feed = public / "feed.json"
            feed.write_text('{"items":[]}')
            sources = public / "sources.py"
            sources.write_text("SOURCES = []")
            main_sitemap = '<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>https://polyemergence.com/en/</loc></url></urlset>'
            weekly_sitemap = '<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>https://polyemergence.com/en/weekly/2026-11-09/</loc></url></urlset>'
            (public / "sitemap.xml").write_text(main_sitemap)
            (public / "weekly-sitemap.xml").write_text(weekly_sitemap)
            for _ in range(2):
                pages.export(public, registry, feed, sources)
                archive.render_sitemap(public, {})
                archive.render_news_sitemap(public, {})
                self.assertEqual((public / "sitemap.xml").read_text(), main_sitemap)
                self.assertEqual((public / "weekly-sitemap.xml").read_text(), weekly_sitemap)
                for locale in ("en", "zh"):
                    home = (public / locale / "index.html").read_text()
                    self.assert_weekly_navigation(home, locale, local_hashes=True)
                    for relative in ("fields/ai/index.html", "tech-news/index.html"):
                        result = (public / locale / relative).read_text()
                        # Field routes rewrite Fields to root; neither renderer
                        # may turn the independent Weekly route into a hash.
                        nav = PrimaryLinks(result).links
                        self.assertIn(f"/{locale}/#fields" if relative.startswith("fields/") else "#fields", nav)
                        self.assertIn(f"/{locale}/weekly/", nav)
                        self.assertNotIn("/wrong/weekly/", result)
                        self.assertIn(f'href="/{locale}/weekly/"', re.search(r"<footer\b.*?</footer>", result, re.S)[0])

    @unittest.skipUnless(shutil.which("node"), "Node is needed for the browser helper fixture")
    def test_locale_helper_preserves_weekly_issue_paths_and_existing_routes(self):
        source = (ROOT / "web/public/app.js").read_text()
        weekly_route = re.search(r"^const routeWeekly = .*;$", source, re.M)[0]
        helper = re.search(r"function updateFieldLinks\(\) \{.*?^\}", source, re.S | re.M)[0]
        fixtures = [
            ["/en/weekly/", None, False, "/zh/weekly/"],
            ["/zh/weekly/2026-11-09/", None, False, "/zh/weekly/2026-11-09/"],
            ["/en/weekly/2026-11-09", None, False, "/zh/weekly/2026-11-09/"],
            ["/en/", None, False, "/zh/"],
            ["/en/fields/ai/", "ai", False, "/zh/fields/ai/"],
            ["/en/tech-news/", None, True, "/zh/tech-news/"],
        ]
        script = "const assert=require('node:assert/strict');\n" + "\n".join([
            "for (const [pathname, domain, routeTechNews, expected] of " + json.dumps(fixtures) + ") {",
            "const location={pathname,origin:'https://polyemergence.com',hash:''}; const state={locale:'en',domain};",
            "const localeLinks=[{dataset:{localeButton:'zh'}}], weeklyLinks=[{}], fieldLinks=[{}];",
            "const $$=q=>q==='[data-locale-button]'?localeLinks:q==='[data-weekly-link]'?weeklyLinks:fieldLinks;",
            weekly_route, helper, "updateFieldLinks();",
            "assert.equal(localeLinks[0].href,expected); assert.equal(weeklyLinks[0].href,'/en/weekly/');",
            "assert.equal(fieldLinks[0].href,'/en/#fields'); }",
        ])
        subprocess.run(["node", "-e", script], check=True, capture_output=True, text=True)

    @unittest.skipUnless(shutil.which("node"), "Node is needed for the service-worker fixture")
    def test_pwa_fetches_weekly_pages_and_styles_from_network_before_cache(self):
        source = (ROOT / "web/public/sw.js").read_text()
        self.assertIn('CACHE_NAME = "polyemergence-v18"', source)
        script = r'''const vm=require('node:vm'),assert=require('node:assert/strict');
const listeners={},fetches=[];
const cache={put:async()=>{},match:async()=>{throw new Error('cache used before network')}};
const context={URL,Request:class{constructor(request,options){this.url=request.url;this.options=options}},
 self:{location:{origin:'https://polyemergence.com'},addEventListener:(name,fn)=>listeners[name]=fn},
 caches:{open:async()=>cache,match:async()=>{throw new Error('cache-first route')}},
 fetch:async request=>{fetches.push(request);return{ok:true,clone(){return this}}}};
vm.runInNewContext(SOURCE,context);
(async()=>{for(const [path,mode] of [['/en/weekly/','navigate'],['/zh/weekly/2026-11-09/','navigate'],['/weekly.css?v=1','cors'],['/weekly.css?v=2','cors']]){
 let response;listeners.fetch({request:{method:'GET',mode,url:'https://polyemergence.com'+path},respondWith:value=>response=value});
 assert.ok(response);await response;assert.equal(fetches.at(-1).options.cache,'no-cache');}
 assert.equal(fetches.length,4);})().catch(error=>{console.error(error);process.exitCode=1});'''.replace("SOURCE", json.dumps(source))
        subprocess.run(["node", "-e", script], check=True, capture_output=True, text=True)


if __name__ == "__main__":
    unittest.main()
