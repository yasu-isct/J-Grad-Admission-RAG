# J-Grad interactive portfolio demo

This branch is the isolated, static GitHub Pages distribution of the public portfolio demo. It is not a backend deployment.

## Audience and scope

Japanese recruiting visitors can open the introduction and then experience the existing Chinese four-step UI. Five fixed sample scenarios cover ISCT Computer Science (2027 April, B schedule) and UTokyo GSFS CBMS (2027 master, general A, April intake, five reviewed material themes). These are historical source snapshots, not current admissions advice.

The original frontend displays saved source-bound responses. Reports are projected by the existing frontend and labelled as samples in both the preview and copied text. Applicant controls are replaced by scenario selection. Saved QA examples are explicitly labelled and do not invoke a model. No arbitrary profile is submitted or evaluated.

## Reuse and data

- Product source: `33a473bdb78a6fc08f8e853c192c951bd115d9ad` on `main`.
- Frontend: the existing four-step HTML, CSS, overview, report/evidence core, and reviewed material presentation modules.
- Samples: existing public PREP-01/PREP-02, EXAM-02B, M19 and QA-01 online-20 records.
- `provenance.json` records exact source paths, hashes and publication transformations.
- Catalog limited to the identities for which saved responses are bundled. Local PDF links removed; official external source links retained.
- No PDF binaries, KB, vector indexes, model weights, runtime workspaces, student records, credentials or API keys are published.
- The demo does not call product endpoints, paid APIs, analytics, or build services at runtime. GitHub Pages handles ordinary site delivery and its access logs.

## Files and maintenance

`index.html` and `showcase.css` introduce the project in Japanese. `app/` holds the reused UI and the separate `demo-bridge.js` / `demo.css` overlay. `data/manifest.json` defines the supported scenarios and their recorded inputs. JSON files hold the published responses. The bridge rejects unsupported API operations and returns only the selected saved results.

Update this distribution deliberately from a reviewed source version; do not publish the project workspace or copy `.env`, runtime directories or source PDFs. A changed source response needs renewed scenario, evidence, report and mobile checks. Rebuilding a model or index is not part of this workflow.

## Rollback

GitHub Pages publishes only the root of `gh-pages`. Restore a previous reviewed distribution by a new commit on this branch, or disable the Pages site. Neither changes the product `main` implementation or the frozen/product runtime assets. This publication does not resume M13 backend deployment.

## License

Application frontend follows the source repository's license. University source excerpts retain their original attribution; no ownership of those documents is claimed.
