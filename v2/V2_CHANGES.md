# v2: contractors confirm the life-saving rules before entering site

v2 is a copy of the v1 project with one requirement added, from the Renewi email thread:

> Contractor must confirm that they have read and understood the life-saving rules before entering
> site. The site needs visibility that the contractor has registered that fact before allowing entry.

Everything else in v1 behaves as before. v1 itself was not changed.

## What it does

1. **The contractor confirms for themselves.** After registering with their invitation link, the
   contractor sees the life-saving rules in their language (English or Dutch so far), ticks one
   statement ("I confirm that I have read and understood...") and presses confirm. Only the holder of
   their private registration link can do this. Staff cannot confirm on someone's behalf.
2. **The record is evidence.** Each confirmation stores who, when, which version of the rules, the
   language, the exact sentence confirmed, and a hash of the rules text shown. It is never edited.
   Confirming is also written to the audit trail.
3. **The site can see it.**
   - The **gate screen** shows "Life-saving rules confirmed" as one of the checks, with the reason
     and next step when it fails.
   - The **people list** has a "Life-saving rules" column (Confirmed, New version to confirm, or
     Not confirmed, with version and time).
   - The **person page** shows the status, the wording they confirmed, and the history.
4. **The system enforces it.** It is a compliance requirement for Vlaardingen, so a person cannot be
   approved, and the gate refuses entry, until they have confirmed the rules *currently in force*.
   Publishing a new version means everyone must confirm again.

## Try it

The demo has a new person, **Ruben Bakker** (scenario "Life-saving rules not confirmed"). Everything
about Ruben is in order except that he has not confirmed. Select him on the gate screen and the
decision is `Access denied: LIFE_SAVING_RULES_NOT_CONFIRMED`. All other demo people are seeded as
having confirmed, so their original scenarios behave exactly as in v1.

To watch a new contractor confirm: create an invitation, accept it, open the registration link,
submit the registration, and Step 2 appears. Without an email provider the link is not delivered
(v1 behaves the same), so for local testing the link has to be issued by hand.

## Run it

Without Docker (what was used to develop and test this):

```bash
scripts/run-without-docker.sh start    # first run installs everything, then starts it
scripts/run-without-docker.sh stop
scripts/run-without-docker.sh reset    # restore the seeded demo data
```

It needs Python 3.12, Node 20 or later and PostgreSQL 17. It keeps everything in `.local/`, with its
own database on port 5544, so it does not touch any other database on the machine. Open
`http://localhost:3000` and sign in as `admin.demo` (the demo password is prefilled).

With Docker, as v1 intended: `docker compose --profile application up --build`. This was not run,
because Docker is not installed on the machine used for development.

Tests: `python -m pytest` (needs the database migrated and seeded; the new tests skip themselves
otherwise and roll back everything they do).

## What changed

| Area | Files |
|---|---|
| Database | `database/migrations/versions/20261009_0015_life_saving_rules.py` adds the rules and confirmation tables and a new compliance kind. It reverses cleanly. |
| Models | `models/life_saving.py` (new), `models/batch3.py`, `models/__init__.py` |
| Logic | `services/life_saving.py` (new). Wired into `services/batch3.py` (the compliance check), `services/batch4.py` (the gate's reason and next step), `services/batch6.py` (re-validation ignores it), `services/people.py` (erasing a person erases their confirmations) |
| API | `routes/life_saving.py` (new): read the rules, confirm, see a person's status. `routes/records.py` (people list carries the status), `routes/workflows.py` and `schemas/workflows.py` (the registration page learns whether the contractor has confirmed) |
| Demo data | `commands.py`, `life_saving_content.py` (new): sample rules, the requirement, confirmations for the existing people, and Ruben |
| Web | `components/workflows/life-saving-rules-confirmation.tsx` and `life-saving-rules-panel.tsx` (new). `invitee-registration.tsx`, `gate-operator-kiosk.tsx`, `app/people/page.tsx`, `app/people/[personId]/page.tsx`, `lib/domain.ts` |
| Tests | `tests/api/test_life_saving_rules.py` (21 new). `test_invitation_registered_names.py` updated for the two new fields in the public registration status |
| Tooling | `scripts/run-without-docker.sh`, and `.local/` added to `.gitignore` |

One fix outside the requirement: `invitee-registration.tsx` removed the secret link from the address bar
and then read it again when React's development mode ran its startup code twice, so the page said the
link was missing. It now remembers the link across the two runs. Production builds were not affected.

A third change outside the requirement: the invitation form used to suggest a visit starting 24 hours
after the demo time (ending at 32 hours), so a demo run hit `VISIT_OUTSIDE_WINDOW` at the gate until the
clock caught up. It now suggests a start at the demo time rounded down to 15 minutes (so the visit has
already begun) and an end 8 hours later (`defaultDateTime` in `invitation-workspace.tsx`). The API's own
rules are unchanged: the end must be after the start and after the demo time.

A second fix outside the requirement: `apps/web/tsconfig.json` set `"target": "es5"`, which the newest
TypeScript (7.x, bundled with current editors) rejects as removed, and it then also rejects the
`import "./globals.css"` in `layout.tsx`. The target is now `es2017` (Next.js's recommendation) and
`noUncheckedSideEffectImports` is `false`. The build, type-check and lint behave the same on TypeScript
5.9 (the project's own version), and the type-check is clean on 7.x. Only type-checking is affected,
since Next.js compiles the code itself.

## Walk-up registration through the entrance QR code

For people the site did not know about in advance (the client's reply: "we often do not know who
enters our site upfront"). It is a second way in, next to the invitation flow. Nothing in the
invitation flow was removed or changed.

1. A fixed QR code at the entrance opens `/arrive/vlaardingen` (the site's name as a short key).
2. The person enters first name, last name, company, email and which of the six categories they are
   (Renewi driver, temporary driver, external driver, maintenance contractor, permanent contractor or
   visitor, the same as an invitation), reads the life-saving rules in their language, ticks the confirmation and
   presses one button. No invitation, no ID document, no approval.
3. The API stores the registration and the confirmation together, or nothing at all: the person
   (reused if the same name and email arrived before), the exact wording confirmed, the rules
   version, language, a hash of the rules shown, the time, and the arrival. Both are audited.
4. The person sees "You are registered" with **a QR code, a Download QR button (saves a PNG) and a short
   reference** to show at the kiosk. After the email check, a copy of the QR is also **emailed** to the
   verified address (as a PNG attachment with the reference and the time it is valid until), so the person
   still has it if they close the page. The send happens after the page is returned and never undoes the
   registration if it fails. Without the email check the address is unverified, so nothing is sent to it.
   The QR holds a random secret; only its hash is stored. Its validity is set per site on the Settings page (12 hours by default).
5. **At the kiosk** (the Gate kiosk page, above the original invitation kiosk, which is unchanged) the
   operator scans that QR with the camera or an uploaded image, or types the reference. A scan fills the
   reference into the box (the QR holds `renewi-walkup:<reference>:<secret>`) and the operator presses Check. The kiosk shows
   name, company, type, when they registered and whether they confirmed the *current* life-saving
   rules, and says "May enter" or "Do not admit" with the reason (rules outdated, person not allowed on
   site, blacklisted). **Let in** records the entry, the operator and the time, and is audited. The
   server re-checks everything when the button is pressed; the screen decides nothing. Letting the same
   person in twice records nothing new.
6. **Email check.** Before step 3, the person gets a 6-digit code by email and must enter it. Nothing is
   stored as a person or a confirmation until the code is right: the form data waits in a short-lived
   pending record (`walk_up_pending`). The code lasts 10 minutes, allows 5 wrong tries (the count is saved
   even though the request fails), can be resent 3 times with a 30-second wait, and one email address
   can have at most 5 codes an hour. Every arrival is checked, even for a returning person, so nobody can
   register as someone else's email. The kiosk shows "Email: verified with a code" or "not verified".
   It needs the mail server from `.env`; with `WALK_UP_EMAIL_CHECK=off` it is skipped, and with it on
   but no mail server the form says so instead of silently skipping. Registrations made before this was
   added show "not verified".
7. **Exit and the shared dashboard.** Walk-up people count in the main dashboard, not in a separate
   section. "Currently present", "Access grants", "Access denials", entries and exits include them (a let-in
   is a grant and an entry, a refusal is a denial). They appear in the same on-site roster, with a
   "Walk-up arrival" note, "No scheduled end" and a working **Record exit**, and in the recent gate
   decisions. "Active visits" is unchanged, because a walk-up person has no visit. The server merges
   them into the finished dashboard result (`merge_walk_ups_into_dashboard`) and into `/api/presence`
   (`walk_up_presence_rows`). The invitation dashboard code and its tests are untouched, and the presence
   list that the expiry features read still excludes walk-ups. Someone who left must register again to
   come back in (they would have to pass the email check again). Entries older than 24 hours without an
   exit are flagged on `/api/walk-up/on-site`.
8. **Refusals are recorded.** When the kiosk says "Do not admit" (rules out of date, not allowed on site,
   blacklisted, already left), a `walk_up.refused` audit event is written with the officer, the person,
   the reasons and `source: system`. A repeated Check on the same person within a minute is not recorded
   again. If the officer turns away someone the records would allow in, **Refuse entry** records the
   reason (the person does not match their ID, nobody could confirm they are expected, or another reason
   with a note) with `source: officer`. A code that matches no recent registration writes
   `walk_up.lookup_failed` with the site and the kind of code, never the code itself. A refusal does not
   lock the person out; it is a record. Counts and the last refusal show on the kiosk card and in the
   arrivals list. Erasing a person erases their refusal events.
9. **Every check at the kiosk leaves a record.** Pressing Check on someone who may enter writes
   `walk_up.looked_up` (the officer, the person, whether the code was read as a QR or a typed reference,
   and whether the person was already in). It never stores the code. A repeat by the same officer within
   a minute is not written again; a second officer's check is. A refused person writes `walk_up.refused`
   and a code that matches nobody writes `walk_up.lookup_failed`, so each check produces exactly one
   kind of record. Erasing a person erases their lookup events too.
10. Staff see it under **Walk-up arrivals** (with an Entry column showing who was let in and when) (the QR code to print, and who arrived in the last 24
   hours with the wording confirmed), in the people list and on the person page, like any invited
   person. Erasing a person erases their arrivals too.

Code: `models/walk_up.py`, migration `20261010_0016`, `services/walk_up.py`, `routes/walk_up.py`,
`schemas/walk_up.py`, `rate_limit.py`, migrations `20261010_0017` (pass and entry columns) and `0018` (email check, exit), `providers/walk_up_email.py`; web `app/arrive/[siteKey]`, `app/walk-up`, `app/gate`,
`components/workflows/walk-up-registration.tsx`, `walk-up-qr-panel.tsx`, `walk-up-gate-check.tsx`,
`walk-up-camera-scanner.tsx` and Tests: `tests/api/test_walk_up.py`. The kiosk was tried in the
browser with an uploaded QR image and with a typed reference. The live camera scan was not tried (no
camera here); it needs https or localhost.

Choices made without asking, easy to change: email is required (a valid contact for emergencies);
the arrival does not need approval; a walk-up registration never attaches to an invited or seeded
person; the public form is limited to 30 registrations per 10 minutes per connection and has a
hidden field that stops simple bots. **Still open:** whether the kiosk check is required for everyone (Harld answered "Yes" to "would
the QR be scanned at kiosk on entering?"), whether admitted walk-ups should also count in v1's roster totals (they are listed beside it), which details Renewi wants collected, retention, and the real rules wording and
legal acknowledgement (Esther's team). The QR link uses `WEB_ORIGIN`, which is `localhost` here, so a
phone cannot open it until the app has an address the phone can reach.

## Private storage in S3

Uploaded identity documents can now be kept in S3-compatible object storage instead of the local
folder: set `STORAGE_PROVIDER=s3` and `S3_ENDPOINT_URL`, `S3_REGION`, `S3_BUCKET`,
`S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`. Files use the same content-addressed names as local
storage, are encrypted at rest (AES256), and are never exposed by URL; only the API reads them. If
any S3 setting is missing the app falls back to local storage and says so at startup. The bucket must
be private and in the EU; creating it and the access keys is up to whoever hosts the app. Code:
`S3Storage` in `providers/storage.py`, tests in `tests/api/test_s3_storage.py`. Tried against a fake
S3 server (store, read, delete, encryption, no public access). Not yet tried end to end through the
upload form, and not tried against real AWS or another provider.

## Decisions to confirm with Renewi

- **The wording is sample text.** The rules and the confirmation sentence were written to show the
  flow. They are not Renewi's approved rules and not approved legal wording. The Dutch is an
  unreviewed translation. The email asks for Renewi's legal and privacy team to advise on the legal
  acknowledgement and privacy. To replace the text, publish a new version (a new `LifeSavingRulesVersion` marked
  current); earlier versions and the confirmations against them are kept.
- **Who must confirm.** It applies to everyone entering Vlaardingen, all six populations. The email
  says "contractor", and Renewi's brief uses "contractors" for third parties in general, but this
  should be confirmed. Narrowing it is a change to one compliance requirement.
- **Per person, not per site.** One confirmation covers every site until the rules change. A per-site
  confirmation would need a `site_id` on the record.
- **A new version means everyone confirms again.** This is the safe reading of "read and understood".
- **Retention.** How long confirmations are kept, and the legal basis for storing them, are not
  decided. Erasing a person removes their confirmations, like the rest of their data.
- **Not changed:** the on-site roster does not show the confirmation (everyone on it has already
  passed the gate check). The invitation flow still starts from an invitation and email.

## Verification

- Existing tests: 87 pass. 1 fails, and it fails identically on untouched v1 (a null-byte filename test).
- New tests: 21 pass. They cover what counts as confirmed, outdated versions, failing closed when no
  rules are published, the contractor's confirmation and its audit record, repeat confirmations, refusal
  without the tick or without a completed registration, the gate's reason and next step, the database
  constraints and the public API.
- All six gate scenarios against the running stack: Alex granted; Sofia, Milan, Noah and Emma denied
  for the same reasons as in v1; Ruben denied for the new reason.
- In the browser: a new contractor registered, read the rules, confirmed, and staff then saw the
  confirmation, its wording and the timeline entry. Ruben was refused at the gate screen.
- Not run: the Playwright end-to-end and Selenium browser suites (they need Docker). They use the named
  demo people, who all remain valid.

## Configurable access validity (per site)

An administrator now sets, on the Settings page and for each site:

- the **default visit length** for planned arrivals (Path A). It pre-fills the end of a new invitation
  (8 hours if never set, 1 to 168 allowed). Staff can still change the end for one invitation.
- how long a **walk-up entry QR stays valid** (Path B), replacing the 12 hours that was fixed in the code
  (12 hours if never set, 1 to 72 allowed).

New invitations and new QR codes use the new numbers. A QR code that was already issued keeps the expiry
it was given, because the kiosk now checks each QR's own stored expiry. Every change is written to the
audit trail (`site_settings.updated`, with the old and new values and who made it).

Changed files: `models/walk_up.py` (`SiteAccessSettings`), migration `20261011_0019`, `services/site_settings.py`,
`routes/site_settings.py` (`GET /api/site-settings`, `GET/PUT /api/site-settings/{site}`; only an administrator
may change it), `services/walk_up.py`, `components/settings/site-access-settings.tsx`,
`invitation-workspace.tsx`, `tests/api/test_site_settings.py`.

## Entry and exit time on the QR

Both QR codes now state when entry opens and when the QR stops working, in the site's own time zone
(Europe/Amsterdam for Vlaardingen), so the person, the email and the gate all show the same clock time.

- **Path A access QR:** the QR card staff see after issuing it, and the email to the invitee, show
  "Entry from" (the visit start) and "Exit by" (the token's expiry).
- **Path B entry QR:** the receipt page and the emailed copy show "Entry from" (when they registered) and
  "Exit by" (registration plus the configured validity).

Changed: `providers/time_format.py`, both email providers, `TokenIssueResponse` (`valid_from`, `site_timezone`),
the walk-up receipt (`site_timezone`), `batch3-workspace.tsx`, `walk-up-registration.tsx`, `lib/domain.ts`.

## Entry and exit time chosen when the access QR is issued (Path A)

When staff issue an access QR, they now see "Entry from" and "Exit by", pre-filled with the visit window.
They can narrow the window but not widen it: the entry time cannot be before the visit starts, the exit time
cannot be after it ends, and the entry must come before the exit. The QR card, the email to the invitee and the
token history all show both times, and the gate refuses the QR before its entry time
(`TOKEN_NOT_YET_VALID`) as it already did after its exit time (`TOKEN_EXPIRED`).

Changed: `access_tokens.valid_from` (migration `20261012_0020`), `issue_access_token`, `TokenIssueCommand`,
the gate's token check in `services/batch4.py`, `batch3-workspace.tsx`. Tokens issued before this have no
entry time and follow the visit start.

## Dashboard: planned and unexpected arrivals side by side

The Overview dashboard now has a table, "Planned and unexpected arrivals", with **On site now**, **Entered**
and **Exited** for planned arrivals (Path A, through an invitation), unexpected arrivals (Path B, the entrance
QR) and the total. It follows the site chosen at the top of the dashboard. The existing tiles are unchanged, and
planned plus unexpected always equals the figure in the tiles. The API returns it as `by_path` on the totals
and on each site. Changed: `services/walk_up.py` (`merge_walk_ups_into_dashboard`), `schemas/batch5.py`,
`operational-dashboard.tsx`, `lib/domain.ts`, and a test in `tests/api/test_walk_up.py`.

## Longest access QR (Path A) and walk-up entry time (Path B)

Two more settings on the Settings page, per site:

- **Longest an access QR may last (hours, 1 to 168, default 24).** Staff still choose each QR's entry and exit
  time, but the exit cannot be more than this long after the entry. When no exit is chosen, the QR runs to the
  visit end or to this limit, whichever is sooner. A longer choice is refused with a clear message (screen and API).
- **Walk-up entry opens after registering (minutes, 0 to 240, default 0).** The QR starts working that long
  after the person registers, and the valid hours (the existing setting) count from that moment. The kiosk
  refuses it before then (`PASS_NOT_YET_VALID`, "Entry opens at HH:MM") and records the refusal.

The kiosk result for a walk-up now shows "Entry from", "Exit by" in the site's time zone and the time left
("opens in 1 min", "4 h 0 min left", "expired"). The receipt and the emailed QR use the same entry time.

Changed: migration `20261012_0021` (`site_access_settings`, `walk_up_registrations.pass_valid_from`),
`services/site_settings.py` (`access_qr_window`), `routes/batch3.py`, `services/walk_up.py`,
`walk-up-gate-check.tsx`, `site-access-settings.tsx`, `batch3-workspace.tsx`, and tests in
`tests/api/test_site_settings.py`.

## Live dashboard and overdue people

- **Live:** the dashboard and its on-site roster refresh themselves every 15 seconds while the tab is visible,
  and the page shows when it was last updated.
- **Overdue:** anyone still on site after they should have left is flagged. For a walk-up person that is their
  QR's exit time. For an invited person it is the earlier of the visit end and their QR's exit time. The roster shows
  an "Overdue by X" badge and the time they should have left, there is a new "Overdue on site" tile, and the
  planned and unexpected table has an overdue row.
- **Nobody drops off the roster.** The invitation projection used to stop listing a person at the visit end, so an invited
  person who never left disappeared from the dashboard. Those people are now found and listed as overdue, and counted
  in "Currently present". Walk-up people were never hidden; the old unused 24-hour "stale" marker is replaced by the
  overdue flag.

Changed: `services/batch5.py` (`ended_only` option, default off), `services/walk_up.py` (`mark_planned_presence`,
`merge_walk_ups_into_dashboard`, `list_on_site`), `routes/batch5.py`, `schemas/batch5.py`, `schemas/walk_up.py`,
`operational-dashboard.tsx`, `lib/domain.ts`, tests in `tests/api/test_walk_up.py`.

## Same capabilities on both paths

Checked end to end against the running app, with John Doe on the planned path and walk-up people on the unexpected path.

| Capability | Planned (Path A) | Unexpected (Path B) |
|---|---|---|
| QR issued | After approval, staff set entry and exit | At registration, entry opens after a delay |
| Validity settings | Default visit length, longest QR | QR hours, entry delay |
| Entry tracking | Gate grant records the entry | Let in at the kiosk records the entry |
| Exit tracking | Record exit on the roster **and at the kiosk** | Record exit on the roster and at the kiosk |
| QR window and time left at the kiosk | **Shown on the scan view and the decision** | Shown on the result |
| Dashboard | On site, entered, exited, turned away, overdue, split by path | Same |
| Overdue flag | Past the visit end or the QR's exit time | Past the QR's exit time |
| Audit trail | Token issue, gate decision, exit | Registration, kiosk check, let in, refusal, exit |

Added in this pass: the QR's entry and exit time and time left on the planned kiosk (scan view and decision, in the site's
time zone), a Record exit button on the planned kiosk decision, and a "Turned away or denied" row by path on the dashboard.
