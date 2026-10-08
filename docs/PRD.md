# timecheck PRD

**Status: transcribed from the planning interview and the /office-hours session of
2026-10-08 between the operator (Dylan Delli Colli) and the release chief; approved by
the operator's delegation ruling of 2026-10-08 (release bead `timecheck-wfn`, comment
4).** The operator owns this document. Changes to product commitments need the
operator's approval, recorded on the release bead.

## Product

timecheck is an openly licensed, provenance-first graph of wristwatches and their
movements. It records which references (watch models) used which calibers in which
years, how calibers relate to one another (base, derivative, clone, grade), what each
caliber's documented attributes are, and, for every one of those claims, the evidence:
a source, an archived snapshot of it, and the exact quote the claim rests on.

In one line: **a sourced watch-and-movement graph that lets anyone start from a watch
and learn what is inside it, what else shares it, and how it changed over time, with
the evidence attached.**

The first release is the database itself and its build: data files in git, compiled
into SQLite with canonical views and a thin command-line interface. Its users are
programmers and agents querying the database directly. A human-facing frontend comes in
a later release, once the data model and build are right.

## Who it is for

- First user: the operator, an enthusiast and prospective buyer of vintage and modern
  mechanical watches who is not a horologist and is building this to learn.
- Goal: open source / community. The people the operator would show it to first are
  forum enthusiasts (WatchUSeek, OmegaForums, r/Watches), a friend about to buy a
  watch, and data/open-source people who would build on the dataset.
- Consumers of the first release: programmers and agents reading the SQLite database
  or calling the CLI.

## The problem and what it displaces

Answering "what movement is in this watch, what else uses it, and how did it change"
today means cross-reading Ranfft DB, Caliber Corner, Wikipedia, brand archives, forum
threads and dealer guides by hand. The reference → caliber → production-year layer
exists only in closed commercial databases. timecheck displaces that manual
cross-referencing with open, sourced, queryable data. It does not displace the parts
and interchange databases (Ranfft DB, Boley, Jules Borel, The Watchmakers App); it links
to them.

### Landscape (as found 2026-10-08; two independent research passes)

- **WatchBase** (Amsterdam, commercial): reference → caliber with families and base
  movements, ~42k watches and ~3.5k calibers claimed (unverified; site blocks reads),
  sold through a paid data feed; no per-fact sources, no open licence.
- **Watch Reference Map**: reference lineages as production timelines for Rolex,
  Omega, Tudor, Patek, AP; no sources, no licence, paid dealer API.
- **Ranfft DB** (ranfft.org): community rebuild of Roland Ranfft's archive; free
  caliber encyclopedia; supporter tier for images, parts catalog, donor sourcing and the
  Shared-Calibers Explorer. Caliber-centric; no watch layer; no API or licence.
- **Caliber Corner**, **EmmyWatch**, **17jewels.info**, **Mikrolisk**, **Vintage
  Watchstraps**, **Watch Movements Archive**, **Grail Watch Reference**: caliber-level
  or history references, all copyrighted, several under EU database right; Grail
  Watch Wiki is CC BY-NC-SA (unusable as a source for open data).
- **Boley**, **Jules Borel**: supplier parts/interchange catalogues. **The Watchmakers
  App**: paid, interchange data from Jules Borel.
- **Wikidata**: essentially empty here (about six movement items, no watch-model class,
  no model → movement property); CC0. **Watch Atlas** (GitHub Pages): ~3.6k
  current-catalogue watches scraped from brand sites, no years, no licence. No open
  dataset on GitHub, Kaggle or Hugging Face links references to calibers.

The gap: **an open licence, a source and archived evidence on every claim, cross-brand
coverage, and "what changed" between calibers.** Those four are what no one offers.

## Use cases

1. **From a watch.** Given a reference or model: its caliber(s) by production year with
   grade (or `unknown`), the caliber's family (base, derivatives, clones, grades) and
   every other reference in the database, across brands, on that caliber or family.
2. **Vintage buyer's view.** For a vintage reference (a 1960s–70s Omega Seamaster): the
   caliber and its family, so the buyer knows what to look for and which related
   calibers exist, with the external references for parts and interchange. Parts are
   not stored.
3. **Lineage.** For a model line (the Rolex Submariner first): references in order with
   their calibers, and the diff of documented caliber attributes across each sourced
   succession, so "what changed and when" is a query.
4. **Cross-maker designation.** The WWII A-11, a USAAF specification built by Elgin,
   Waltham and Bulova with their own calibers: from the designation to each maker's
   references and calibers side by side.
5. **Evidence filter.** Any of the above restricted to claims with primary-source
   evidence, showing which familiar histories survive.
6. **Later, if at all: value investing.** Join market price observations to find
   watches whose caliber also sits in far more expensive watches. Out of the first
   release; the graph must not preclude it.

## What would make it wrong

- Any claim without evidence, or a claim an agent wrote from memory. The builders are
  language models; an unsourced "fact" is a guess presented as reference data.
- A citation that cannot be verified: a dead link, a changed page, a quote that is not
  in the snapshot. Provenance must be archived and machine-checkable.
- Silent conflict resolution: two sources disagree and the product shows one as if
  settled.
- Conflating a caliber number with the movement: an ETA 2824-2 in Standard grade and
  one in Chronometer grade are the same caliber and different movements. Grade is part
  of identity; `none` (the maker offers no grades) is distinct from `unknown`.
- A reference that used several calibers across its production shown with one.
- Bulk or systematic extraction from a copyrighted database, however small each piece.
- A pleasant interface over thin or fabricated data (which is why the interface waits).

## Out of scope (for the product as a whole, until the operator says otherwise)

- Market prices and valuation.
- Parts and interchange data of our own (link out instead); agentic parsing of supplier
  catalogues is a possible later release.
- Hosting, accounts, community editing through a UI. Contributions are pull requests.

## Data sources and policy

Every claim carries evidence: source (URL, publisher, licence), a pinned archived
snapshot and its hash, the exact quote and a locator, the retrieval date, the source's
trust tier, and a verification status. No agent writes a catalogue claim from memory; a
claim it cannot cite is not entered.

Trust tiers (operator ruling 2026-10-08: two tiers only):

- **Primary**: manufacturer pages and technical documents (Rolex, Seiko, Omega product
  and archive pages; ETA, Sellita, Miyota, Seiko caliber sheets), official standards or
  military specifications, brand archives (e.g. Omega's vintage database), dated
  catalogues and advertisements.
- **Secondary**: Wikipedia and Wikidata; enthusiast and community references (Ranfft
  DB, Caliber Corner, EmmyWatch, 17jewels.info, Mikrolisk, Vintage Watchstraps, Watch
  Movements Archive, Pocket Watch Database and maker serial databases, forums, dealer
  guides). A claim with only secondary evidence is shown as such.

Reuse class, a property of the source, not of its tier:

- **Open** (Wikidata CC0; Wikipedia CC BY-SA with attribution for facts; public-domain
  government documents): may be loaded by extractors.
- **Cite-only** (every copyrighted site above, several under EU database right):
  individual claims cited by URL, snapshot and quote; no systematic extraction in any
  release unless the operator obtains permission; a per-domain cap on the share of
  evidence any one cite-only site may supply, enforced in CI.
- **Banned**: sources under a non-commercial licence (e.g. Grail Watch Wiki).

The repository never stores full-page text of a cited source; only the short quote,
locator, archive URL and snapshot hash.

Conflicts between sources are stored as competing claims and marked disputed; they are
never merged.

## Licence

Data (`data/`): Open Database License (ODbL) 1.0 with the Database Contents License
(DbCL) for contents. Code: MIT. Contributors sign off under the Developer Certificate
of Origin. Operator ruling 2026-10-08: ODbL chosen over CC0; share-alike protects the
community's work from silent absorption. Consequence noted: pushing timecheck data
into Wikidata (CC0) would need a separate CC0 release by the contributors concerned.

## Roadmap

- **v1 (this release, brief in `docs/releases/v1.md`)**: the claim model and schemas,
  the build that verifies evidence and compiles SQLite with canonical views, the CLI,
  documentation for programmers and agents, the seed, and a GitHub repository with CI.
  Seed families: Rolex Submariner; Seiko Presage and the other Seiko lines sharing its
  4R/6R/6L calibers; Omega Seamaster 1960s–70s; ETA 2824-2/2892-A2/7750 with their
  Sellita clones and host references across brands; the A-11 from Elgin, Waltham and
  Bulova. Depth per family is set by the measured cost of a timed ten-reference pilot.
- **Candidates after v1**: the frontend (a lineage timeline with an evidence drawer; a
  wireframe exists); an MCP server for agents; more lines and brands; price
  observations and the value query; a parts slot seeded from citable references;
  agentic supplier-catalogue parsing; outside contributions and a human maintainer
  review flow; contribution of links to Wikidata.

## Success

- A programmer or agent can answer use cases 1–5 for the seed from a clean checkout
  using only the documentation, the SQLite file and the CLI.
- 100% of claims carry evidence; a sampled audit of claims against their archived
  snapshots finds them faithfully transcribed.
- Disputes, unknowns and coverage gaps are visible, never hidden.
