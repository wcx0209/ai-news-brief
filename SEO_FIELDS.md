# Field SEO and navigation

Updated: 2026-11-12. Each registered field has its own English and Chinese
landing page at `/{locale}/fields/{domain_id}/`. The homepage presents those
fields before displaying any news; field pages display only their own current
48-hour briefing.

| Field ID | English search intent | Chinese search intent |
| --- | --- | --- |
| ai | AI news; artificial intelligence news | AI 新闻；人工智能动态 |
| programmable_life | biotech news; synthetic biology | 生物技术新闻；合成生物学；可编程生命 |
| energy_storage | renewable energy news; energy storage | 新能源新闻；储能技术；电池 |
| robotics_autonomy | robotics news; autonomous systems | 机器人新闻；具身智能；自主系统 |
| quantum_technology | quantum computing news | 量子计算新闻；量子技术 |
| space_economy | space news; commercial space | 太空新闻；商业航天 |
| advanced_materials | advanced materials news; nanotechnology | 新材料新闻；纳米技术 |
| neurotechnology | neurotechnology news; brain-computer interfaces | 神经科技新闻；脑机接口 |
| climate_water_environment | climate technology news; water technology | 气候科技新闻；水处理；环境工程 |
| agrifood_technology | agritech news; food technology | 农业科技新闻；食品技术 |
| advanced_manufacturing | advanced manufacturing news | 先进制造新闻；产业基础设施 |

These are editorial keyword targets, not measured search volumes or ranking
claims. Each page contains a unique title, H1, description, canonical URL,
reciprocal locale links, a field overview, source links, and visible static news
summaries. JavaScript hydrates the same news containers. CollectionPage,
BreadcrumbList and ItemList data describe the content actually on that page.

Empty fields keep a useful scope and source page, with an honest empty state;
they are never filled with old or unrelated stories. The generator reads the
registry rather than a fixed page count, with editable bilingual SEO copy and a
fallback for newly registered fields.

Every field-page export first synchronises both homepages' static field cards
and footer field links from the same registry. Adding a field therefore updates
the crawlable entry links, both language pages and the field sitemap together,
without requiring JavaScript or manual navigation edits. Registry text is
HTML-escaped, field IDs are validated before any output is changed, and the
cloud workflow commits the refreshed homepages alongside the generated pages.

`sitemap.xml` includes the current 22 locale URLs; `field-sitemap.xml` is generated
from the registry every cloud run and declared in `robots.txt`. The existing
main sitemap is already registered successfully in Google Search Console.

Verification on 2026-11-12: Google processed the new field sitemap successfully
and discovered all 22 URLs. A live URL Inspection test of the English quantum
page reported that Google can access and index the page, with one valid
Breadcrumbs item. This is crawl/indexability verification, not confirmation that
the newly published pages already rank in search results.

Daily AI News historical routes contain AI stories only. Other story-angle
pages and permanent archives may span fields and identify that scope explicitly.
Archive summaries link back to their field page. These internal links let
readers and crawlers follow the same structure.

After publication, use Search Console's page and query reports to assess each
`/fields/` path. A deployed page, successful sitemap fetch, indexed page and
ranking improvement are separate observations; deployment alone does not prove
the last two.
