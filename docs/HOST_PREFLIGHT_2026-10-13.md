# BOX2 — Host preflight evidence and approval gates (2026-10-13)

**Source:** Owner supplied Codex's read-only `PREFLIGHT.md`, `PUBLIC_EVIDENCE.md` and hosting-support evidence request, prepared on October 13, 2026. These are **Codex-reported public client tests and operator/panel-reported host facts**, not independent server access or permission to deploy. The original local `public-browser-evidence.json` was referenced but **not supplied/committed**. The full 410-line local preflight report was reviewed in the conversation; this repository note captures actionable conclusions rather than claiming all local artifacts were imported.

**Decision: HOLD production cutover.** No server changes, staging site, merge, mail, OBS action, public booking activation or venue publication are established by these tests. Existing PR foundation `044cd1ee7bd1d75bbd7cfdb0bc0bf416b9d7c0d2` (#1); candidate app `0f7de0e2e9b4a85c9018cfef8ec97c50ae6836d0` (#5).

## Public evidence (read-only, Codex-observed)

| Check | Result | Limit |
| --- | --- | --- |
| DNS | `box2.yurrmom.com` A `91.204.209.207` (TTL 3600); no AAAA/CNAME answer in queried resolver | Not all resolvers/edges |
| **HTTP root** | **HTTP/1.1 200 OK, no `Location`, served by LiteSpeed** | Confirmed insecure-origin exposure on HTTP; not a diagnosis of the old HTTPS warning |
| HTTPS root | HTTP/2 200, TLS 1.3, hostname match, certificate chain verified | Only tested current origin and initial page |
| Certificate | Let's Encrypt YE1 wildcard `*.yurrmom.com`, also SAN `yurrmom.com`; validity 2026-10-09 19:52:17Z through 2027-01-07 19:52:16Z | Panel certificate state alone is not a browser-security guarantee |
| Browser | Fresh Chrome 155.0.8059.40 secure context, no reported issue IDs; document, CSS, JS served HTTPS; two form targets resolved HTTPS; no mixed content found in initial page | Not every route/form/profile; owner's earlier `Not Secure` cause still **unknown** |
| HTTP browser | Final URL stayed HTTP; origin insecure; HTML/CSS/JS all HTTP | Relative legacy POST APIs inherit insecure origin; no form submission tested |
| Parent site | `https://yurrmom.com` currently served a secure HTTP/2 200 Next.js homepage | Smoke test only, not PHP/account regression |
| App tests | PR #5 previously passed PHP 8.2 and 8.5 backend + responsive Chromium CI; local synthetic backup/restore/retention test rerun | No real host PHP, SQLite, cron, SMTP, device or staging proof |

Strict curl/OpenSSL certificate checks reportedly succeeded without disabling verification. The observed served certificate SHA256 fingerprint was:
`09:A2:01:99:5A:CA:57:F5:D2:3A:76:D9:90:25:C6:BC:B7:01:6F:DC:16:5B:73:D0:1D:48:1E:88:A8:E8:02:22`.
Do **not** conclude expired TLS, mixed content, interception or an old cache issue without affected-device evidence. The first page audit deliberately blocked non-GET/HEAD requests and did not inspect login/booking actions. No HSTS was observed; HSTS absence alone does not explain a HTTPS downgrade.

## Hosting unknowns — do not infer from the panel

DirectAdmin displayed BOX2 subdomain root `/domains/box2.yurrmom.com/public_html`, PHP Selector account-global **8.5**, PDO SQLite/mbstring/fileinfo enabled and domain PHP isolation disabled. These are account-panel observations **not** proven absolute OS paths, web PHP SAPI/CLI binaries, filesystem boundaries or actual domain isolation. Real cron jobs, permissions, locking, restoration and mail remain untested.

Before any exact-path installer, populate this ledger using authorized hosting-panel/provider evidence:

| Symbol | Meaning | Status |
| --- | --- | --- |
| `L_HTTP` / `L_HTTPS` | True served roots, realpaths, `private_html`, aliases and symlinks | UNVERIFIED |
| `L` | Actual launcher-serving `public_html` directory | UNVERIFIED |
| `D` | `dirname(L)` physical parent | UNVERIFIED |
| `A` | Private sibling `D/box2` and PHP readable entrypoint `A/public/index.php` | UNVERIFIED |
| `P` | Persistent, writable private storage outside **all** served docroots and aliases | UNVERIFIED |
| `S` | Independently protected preview root | NOT CREATED |
| `PHP85` | Actual PHP 8.5 CLI binary/ini/extensions; compare web-SAPI | UNVERIFIED |
| Identity | PHP/cron UID/GID, ACL/open_basedir/CageFS, quota, atomic-rename support, SQLite locking | UNVERIFIED |
| Legacy inventory | Hidden files, database and WAL, uploads, configs, active bookings/links/outbox, cron | UNVERIFIED |

The launcher `deploy/public_html/index.php` references `dirname(__DIR__).'/box2/public/index.php'` from the true serving root. **A panel-relative path cannot be blindly turned into `~/box2`**. If `A` falls inside any served root, is blocked by open_basedir or cannot use private persistent storage, stop and redesign layout rather than relax security account-wide or place DB/config in public.

## Conditional design — NOT approved for installation

- **Future live:** public `L` contains only reviewed launcher, routing `.htaccess` and safe `assets/`. Private source is `A`; separate `P/production/data` stores SQLite, private uploads, private logs/backups. Never overlay a legacy site with old endpoints that bypass the new front controller.
- **Future preview:** separate approved `box2-preview.yurrmom.com` (wildcard SAN must be independently verified) with private `S`, distinct code/config/storage/secrets, **HTTPS plus server-side authentication or IP restriction before serving anything**, synthetic data only. Preview remains `allow_bookings=false`, `venue_public_enabled=false`, `mail_transport=disabled`, `allow_house_continuity=false`. No real guest data/creds or old restored DB in an internet-facing preview.
- **Scoped HTTPS repair:** after vhost/redirect authority is verified and **separately approved**, redirect BOX2 HTTP GET/HEAD to the fixed HTTPS host, preserve path/query safely, and reject sensitive HTTP POSTs before PHP. Do not rely on arbitrary user-supplied Host/forwarded headers or impose parent-domain redirects/HSTS. Confirm no redirect loops, secure parent, mixed-content regressions, insecure forms or leaked logs. **No rewrite/change is made by this document.**

## Legacy data and staged acceptance

1. Obtain nonsecret provider facts using [HOST_EVIDENCE_REQUEST_2026-10-13.md](HOST_EVIDENCE_REQUEST_2026-10-13.md). A separate snapshot/restore approval may be required.
2. Inventory old BOX2 `public_html` including hidden files, configs, PHP APIs, uploads, SQLite database/journals and future booking/outbox state. The new `migrations/001–003` upgrade the new app schema, **not an arbitrary legacy DB**. Decide compatibility/import/notification explicitly. Do not point current migrations at legacy data.
3. Take a provider-consistent private legacy backup and **rehearse an isolated restore** before any cutover, including jobs, permissions and actual rollback timing; don't place backups in an accessible directory.
4. Protected staging first: verify PHP 8.5 web/CLI, SQLite locking, private filesystem and cache/session isolation; synthetic booking 5/10/15, private fail-closed capture, Top 5 rights, token/CSRF/admin, denied public PII access, migrations, cron queue disabled, HTTPS and Twig/Twitch embed requirements where applicable. Positive synthetic bookings may require a *separately approved isolated fixture*; standard staging gates stay OFF.
5. Only with separate owner approval and a proven rollback, consider closed-gate cutover. Actual public booking/venue entry/mail/house continuity/ads and OBS device changes require their **own** approval. Physical venue, parking and room privacy verification remain Issues #2/#3.

### Minimum next action
**Request verified absolute roots, PHP web + CLI runtime, private storage/isolation, cron permissions and provider backup/restore feasibility.** Diagnose the original affected Chrome session only if it still reproduces; don't block evidence collection on an unexplained historical warning. Keep HTTP redirect remediation scoped and separately approved.
