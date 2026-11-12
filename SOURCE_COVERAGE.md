# Emerging-field source coverage

Updated: 2026-11-12. The nine fields below each have six configured core sources
(54 total), alongside the existing AI and programmable-life sources. The complete
seed catalog contains 175 feeds; this is a configured-source count, not a count
of publishers or a promise of daily articles from every source.

| Field | Core sources |
| --- | --- |
| Energy & storage | MIT Energy; Energy-Storage.news; EIA Today in Energy; UK Atomic Energy Authority; pv magazine Global; Utility Dive |
| Robotics & autonomy | MIT Robotics; The Robot Report; IEEE Spectrum Robotics; Robohub; Clearpath Robotics; NVIDIA Robotics |
| Quantum technology | IBM Quantum; Nature Quantum Information; AWS Quantum Technologies; D-Wave News; The Quantum Insider; Quantum Computing Report |
| Space economy | NASA News; NASA JPL; SpaceNews; Spaceflight Now; European Spaceflight; JAXA Press Releases |
| Advanced materials | Nature Materials; MIT Materials; AZoM Materials News; Advanced Science News; Phys.org Nanotechnology; NIMS Materials News |
| Neurotechnology | MIT Neuroscience; Nature Biomedical Engineering; BrainGate; Nature Brain-Machine Interfaces; Neuroscience News Neurotech; Neurotech Newsletter |
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

The canonical tuples are in `scripts/bootstrap_sources.py`. Source seeding uses
one transactional bulk upsert, preserving existing source IDs and fetch times.
Review the per-source `FETCH STATISTICS REPORT` in each cloud run for successful
ingests, duplicates, age filtering, relevance rejection and network failures.
Repeated access failures deserve a replacement; an absent article in today's
brief alone does not.
