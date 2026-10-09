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
- **Not built:** the walk-up flow described in the client's email (scan a QR code at the kiosk, register
  with name and company, read the rules, acknowledge, with no prior invitation). v1 starts from an
  invitation, and so does this change. That flow is the likely next step. Also not changed: the
  on-site roster does not show the confirmation (everyone on it has already passed the gate check).

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
