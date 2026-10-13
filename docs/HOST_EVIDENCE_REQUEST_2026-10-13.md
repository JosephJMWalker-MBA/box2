# BOX2 — Hosting support evidence request (2026-10-13)

**Preflight only.** Please do **not** change PHP, document roots, DNS/TLS, live files, cron, permissions, caching or email configuration. No passwords, private keys, signing secrets, account tokens, guest records, raw environment dumps or public `phpinfo()` pages are needed.

Site: `box2.yurrmom.com`; hosting panel DirectAdmin (Hostinger). Panel shows document root `/domains/box2.yurrmom.com/public_html`, account-global PHP Selector 8.5, PDO SQLite/mbstring/fileinfo selected and per-domain PHP isolation disabled. These panel values must not be treated as verified realpaths or runtime settings. Independent public checks found HTTPS 200 with valid TLS/certificate, but **HTTP 200 without redirect**. Please report existing settings rather than changing them.

Please supply the following **nonsecret facts with timestamp/source**:

1. Actual *absolute* HTTP/HTTPS document roots, realpaths, any `private_html` split, symlinks/aliases and overrides. Confirm whether the displayed path is account-relative/chrooted; list **all** publicly served roots in the account, so private app/database paths can be proven non-web-accessible.
2. Can PHP read the physical sibling directory `D/box2` where `D=dirname(true BOX2 public_html path)`? Launcher references `dirname(__DIR__).'/box2/public/index.php'`. Identify applicable `open_basedir`/CageFS limits and the suitable private persistent data root accessible to web PHP and cron. Do not create any directory or relax a restriction yet.
3. Actual **web-PHP** version, SAPI/handler, ini path, HTTPS server flag, available PDO drivers including sqlite, SQLite library, mbstring/fileinfo/OpenSSL/sessions; separate **PHP 8.5 CLI** executable/ini/extensions. Identify session/upload temp paths, size limits, applicable disabled functions and protected error log. No public phpinfo or dump of sensitive environment values.
4. Web PHP and cron UID/GID, ownership/ACL/traversal requirements, same-account site separation, symlink policy, filesystem type, quotas, SQLite locking and atomic rename support. Private directories 0700/private files 0600 are desired subject to actual identity; avoid `chmod 777`.
5. DirectAdmin **Cron Jobs** availability, syntax, minimum cadence, timezone, log destination and mechanism for private PHP CLI setup/migration/backup/restore if SSH is unavailable. Identify existing BOX2 jobs but do not modify them.
6. Actual LiteSpeed edition/handler/rewrite + auth support, cache overrides, TLS termination/HTTPS propagation, certificate binding/renewal and support for a **separately approved HTTPS-authenticated preview hostname**. Please identify why HTTP currently returns 200 and what *BOX2-only* redirect approach is supported; **do not apply it yet**.
7. Whether a consistent protected **legacy backup** can capture hidden files, config/includes, SQLite DB/journals, uploads outside the served root, permissions, cron/vhost settings and a safe isolated restore. State any temporary write freeze needed; don't write backups into public web directories or run them without approval.

If facts require shell access, a diagnostic probe or any change, please state the minimum narrowly scoped approval needed rather than performing the action.

We are preparing a **separately authorized protected staging rehearsal**, not requesting immediate deployment, site replacement, mail, marketing or public booking activation.
