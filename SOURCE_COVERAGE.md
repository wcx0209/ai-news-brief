# Emerging-field source coverage

Updated: 2026-11-14. The nine fields below each have six configured international core sources
(54 total), alongside the existing AI and programmable-life sources. The complete
original seed catalog contains 175 feeds before the Chinese additions below; this is a configured-source count, not a count
of publishers or a promise of daily articles from every source.

| Field | Core sources |
| --- | --- |
| Energy & storage | MIT Energy; Energy-Storage.news; EIA Today in Energy; UK Atomic Energy Authority; pv magazine Global; Utility Dive |
| Robotics & autonomy | MIT Robotics; The Robot Report; IEEE Spectrum Robotics; Robohub; Clearpath Robotics; NVIDIA Robotics |
| Quantum technology | IBM Quantum; Nature Quantum Information; AWS Quantum Technologies; D-Wave News; The Quantum Insider; Quantum Computing Report |
| Space economy | NASA News; NASA JPL; SpaceNews; Spaceflight Now; European Spaceflight; JAXA Press Releases |
| Advanced materials | Nature Materials; MIT Materials; AZoM Materials News; Advanced Science News; Phys.org Nanotechnology; NIMS Materials News |
| Neurotechnology | MIT Neuroscience; Nature Biomedical Engineering; BrainGate; Nature Brain-Machine Interfaces; Neuroscience News Neurotech; The Transmitter |
| Climate, water & environment | MIT Climate; Carbon Brief; Nature Water; International Water Management Institute; Yale Environment 360; Environmental Protection |
| Agriculture & food technology | MIT Food & Water; AgFunderNews; Future Farming; FoodNavigator; Green Queen; Good Food Institute APAC |
| Advanced manufacturing | NIST Manufacturing; MIT Advanced Manufacturing; Siemens Blog; Fraunhofer IFF; 3D Printing Industry; TCT Magazine |

## Verification and operation

- The 36 additions returned parseable feed entries with original publication
  dates using `curl_cffi` Chrome impersonation and `feedparser`. They require
  neither a paid API nor a logged-in browser.
- NASA's old breaking-news URL is migrated in place to its current
  `https://www.nasa.gov/news-release/feed/` endpoint, retaining historical source
  IDs and article references.
- The Robot Report returned 403 from the verification network. Retain it as an
  existing source and check its result in the cloud collector; an accessible
  feed on one network does not guarantee access from every network. IBM
  Quantum's existing HTML adapter was rechecked and returned eight dated items.
- Low-cadence official sources (including BrainGate, NIMS, JAXA, Fraunhofer IFF
  and AWS Quantum) remain valuable for original announcements. A valid feed
  without a recent item does not imply a failed collector.
- The initial Neurotech Newsletter feed passed local verification but returned
  403 from GitHub Actions. The Transmitter replaces it in the core catalog;
  the old URL is excluded by the free deployment profile without deleting its
  source record or historical articles.
- Broader publications pass a title-level relevance gate before the source item
  cap and LLM summarisation. This excludes generic oil-market, dining, wildlife
  and retail-security stories while retaining registered technology fields.
- The free profile considers one candidate per source each run (three for
  programmable life). Network work uses two workers; Gemini requests remain
  serialized with the existing 15-second interval. Source confidence does not
  directly increase an article's importance score.
- The public brief still uses original publication time and a 48-hour window.
  The collector may inspect first-party announcements up to seven days old;
  these do not enter the public brief once outside that 48-hour window.
- All scheduling, source seeding, collection and publishing run in GitHub
  Actions at 06:00 and 18:00 UTC. Local verification is not a runtime dependency.

## Maintaining the catalog

The international tuples are in `scripts/bootstrap_sources.py`; Chinese specialist
manifests are in `config/sources/china-*.json`. `src/source_catalog.py` joins them
for both cloud seeding and read-only static export, without executing database
code during page rendering. Source seeding uses
one transactional bulk upsert, preserving existing source IDs and fetch times.
Review the per-source `FETCH STATISTICS REPORT` in each cloud run for successful
ingests, duplicates, age filtering, relevance rejection and network failures.
Repeated access failures deserve a replacement; an absent article in today's
brief alone does not.

## Chinese specialist coverage

The additions total 30 configured sources (17 research institutions, eight
company channels and five specialist media), taking the complete catalog to
205. Each of the ten non-AI fields has three Chinese additions alongside its
six international core sources. Counts refer to configured channels, not unique
parent institutions or guaranteed daily articles.

| Field | Chinese additions |
| --- | --- |
| Programmable life | CAS Tianjin Institute of Industrial Biotechnology; CAS SIAT Institute of Synthetic Biology; CAS Institute of Microbiology |
| Energy & storage | Gotion High-Tech; CAS Institute of Plasma Physics; China Energy Network storage |
| Robotics & autonomy | SIASUN; DOBOT; Leaderobot |
| Quantum technology | CAS Quantum Innovation Institute; Beijing Academy of Quantum Information Sciences; CNQT |
| Space economy | LandSpace; Galactic Energy; CASC |
| Advanced materials | CAS Institute of Metal Research; CAS Ningbo Institute of Materials Technology and Engineering; CAS Shanghai Institute of Ceramics |
| Neurotechnology | NeuroXess; CAS Center for Excellence in Brain Science and Intelligence Technology; CAS SIAT Brain Cognition and Brain Diseases Institute |
| Climate, water & environment | CAS Institute of Urban Environment; Agro-Environmental Protection Institute; H2O China |
| Agriculture & food technology | CAAS Institute of Plant Protection; CAAS Institute of Food Science and Technology; CAAS Cotton Research Institute |
| Advanced manufacturing | Farsoon Technologies global official news; Nanjixiong; CAS Changchun Institute of Optics |

Every non-AI field now has a dedicated regional manifest rather than depending
on incidental reporting by broad Chinese technology media. Manifests record the
publisher, region (`CN`), source kind, editorial field, verification date and
host-scoped HTML adapter. Research institute announcements are first-party
releases, not automatically peer-reviewed research papers. Media reporting is
not labelled as an official release. Configured sources are not guaranteed to
publish daily or to have a story within the current 48-hour brief.

The adapters are browserless and use only public publisher pages. Chinese CMS
`ArticleTitle` / `PubDate`, explicit article selectors, Chinese or dotted dates,
and `Asia/Shanghai` local publication time are supported. Per-index URL patterns
exclude navigation, unrelated sections and known paid previews. Query-based
article identifiers are preserved. The new adapters inspect at most eight links
and retain at most three dated, readable articles; the existing downstream
per-source caps and broad-source relevance gates still apply. Generic company
awards, institutional events and unrelated announcements are not guaranteed a
place in the feed merely because the publisher is Chinese.

Do not synthesize a publication timestamp from the crawl time. A date-only
publication is represented as midnight in the publisher's timezone. A known
article-list publication date can be used only when it is scoped to that same
article card, never borrowed from another story or a page footer.

Run the **China specialist source health** GitHub Actions workflow for live
verification from the cloud network. It saves a 30-day JSON artifact and a job
summary with dated/readable counts and latest source dates. A dated older item
proves that parsing works; it does not imply that a feed is current. A failed
probe does not lower quality thresholds or trigger a browser/paywall bypass.
The health command explicitly refuses local execution and makes no database
or LLM calls; the optional, separate seeding step activates the checked catalog.
