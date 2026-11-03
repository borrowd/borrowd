# Changelog

Notable changes to Borrow'd, grouped by weekly release. Releases go out on
Mondays (staging → prod), so each heading is a release Monday. Its entries are
the changes merged to `main` from the previous Tuesday through that Monday.

Entries before **2026-11-02** were backfilled from `main`'s git history. They
are approximate: a change may sit a week off from when it actually reached
prod, and weeks with no merges are left out. PR numbers are included so you can
look up details.

Sections: **Added** (new capability), **Changed** (behavior or UX changes to
existing features), **Fixed** (bug fixes), **Under the hood** (infra, tooling,
refactors, security bumps; no direct user-facing change).

---

## Unreleased (2026-11-02)

### Changed
- Form layouts now use the same frame everywhere (UX consistency audit 4/4) (#652)

### Fixed
- Redirect loop at the beta gate after signing in (#662)

## 2026-10-26

### Added
- "Group" filter on the item search page (#647)
- An "add an item" nudge for people who join a group through an invite link (#646)
- AI use policy for contributors (#637)

### Changed
- Simpler sign-in flow (#644)
- Updated messaging UI (#639)
- Mobile nav drawer reorganized, with a profile header, a footer section and an unread dot (#643)
- UX consistency audit, parts 1–3: community requests, groups & inventory, and messaging (#649, #650, #651, #642)

### Fixed
- Signup page header and footer now stay pinned to the edges of the viewport (#645)

### Under the hood
- Analytics: record how members joined a group and when they left (#635)

## 2026-10-19

### Added
- Notification onboarding: users are prompted to set up notifications (#627)
- Site-wide PWA service worker (#618)

### Changed
- Onboarding nudge notifications no longer send emails (#631)

### Fixed
- Push notification permission settings (#620)

### Under the hood
- Analytics: record transaction status history and real user activity (#633, #634)

## 2026-10-12

### Under the hood
- Item and transaction status names consolidated into one vocabulary (#622)
- New `Transition` table, not used yet (#623)
- Management command to audit item and transaction state (#625)

## 2026-10-05

### Added
- Dark-mode favicon and PWA icons (#621)

### Changed
- Onboarding now covers community requests and messaging (#616)

### Fixed
- Login page title (#617)

## 2026-09-28

### Changed
- New group members land on the item list after joining (#615)

### Fixed
- The item owner's name is no longer stored for or shown to viewers who aren't entitled to see it (#613)
- Outbound email retries temporary SMTP failures (#612)

### Under the hood
- The Claude Code review workflow was posting nothing on PRs; fixed (#614)

## 2026-09-21

### Added
- Messaging UI: read/unread states and badges, a messages hub with tabs and conversation item cards, and filters (#582, #583, #584)
- Notifications for new messages (#585)
- Messaging settings tab (#587)
- PWA manifest and icons, so the app can be installed (#605, #611)

### Changed
- Settings and profile pages redesigned (#586)

### Under the hood
- Security patch bumps: Django 5.2.17, Pillow 12.3.0, sqlparse, urllib3, aiohttp, cryptography and JS build tooling (#600–#604)
- Management command to backfill messaging data (#588)

## 2026-09-14

### Added
- Start a conversation from an item detail page, or start a borrow request from a chat (#578)
- Conversations show which group and listing they're about, plus the item's conversation history (#576, #580)

### Changed
- Updated FAQ (#579)

### Fixed
- Existing chats keep working when messaging is turned off or the item is deleted (#575)
- Elements no longer flash on screen before Alpine.js loads (`x-cloak`) (#574)

### Under the hood
- Fewer queries for conversations on the item detail page (#581)
- Automated Claude Code review on PRs (#594)

## 2026-08-31

### Added
- Messaging chat UI (#554)

### Changed
- A profile photo saves as soon as it's uploaded (#560)
- The photo upload limit went from 5 MB to 10 MB (#565)

### Fixed
- Another fix for the CSRF error (#571)
- The back button now returns to the right page from forms (#567)
- Permission groups drifting out of sync with group memberships (#570)

### Under the hood
- Item state is precomputed in bulk to avoid extra database round trips (#539)
- Missing migration for group logo/banner validators (#573); CI fixes (#569)

## 2026-08-24

### Added
- Community Requests: members can post what they need and mark requests fulfilled (#548, #555)
- An FAQ inside the app (#564)
- People with a pending group membership can cancel their request (#561)

### Changed
- The group invitation page shows the group banner instead of the logo (#556)
- Sentence case used across the whole app (#558)

### Fixed
- Cookies now set the `Secure` attribute (#559)
- Additional CSRF fix (#557)
- Anonymous requests are handled before the object lookup in permission checks (#566)
- Group visibility when permissions are removed in bulk (#529)

## 2026-08-17

### Changed
- Styling updated to match Figma (#552)

### Fixed
- Stale CSRF token in htmx requests after the token rotates at login (#553)
- The delete avatar button in its modal did nothing (#551)

## 2026-08-10

### Added
- Messaging core (backend v1) (#544)

### Changed
- Lenders can confirm an item was returned without waiting for the borrower to confirm (#542)

### Under the hood
- More reliable E2E tests, and CI now reports test durations (#526)

## 2026-08-03

### Added
- In-app notifications UI (#540)

## 2026-07-27

### Changed
- Onboarding updated to explain per-item group sharing (#541)

## 2026-07-20

### Added
- Per-item group sharing: choose which groups each item is shared with (#523)
- Push notification channel (#509)
- Item giveaway, part 3 (#519)

### Changed
- Updated descriptions of the profile transparency metrics (#524)

### Under the hood
- E2E test fixes (#522)

## 2026-07-13

### Added
- Lending and borrowing stats on profiles (#520)

## 2026-07-06

### Added
- Loading state while uploads are in progress (#510)

### Under the hood
- Finished the `mypy --strict` cleanup (#517, #518)

## 2026-06-29

### Added
- Item giveaway, parts 1 and 2: give an item away instead of lending it (#516)
- Notifications backend (#503)

### Under the hood
- mypy django-stubs plugin (#513); E2E test fixes (#514)

## 2026-06-22

### Changed
- The delete button was removed from the edit group form (#506)
- Group member counts include active members only (#511)

### Fixed
- Pages no longer briefly appear unstyled in local development (#512)

### Under the hood
- Python/Playwright E2E test suite with Allure reporting (#495)

## 2026-06-15

### Added
- Item return flow (#502)
- A "Join group" call to action on the item search page (#497)

### Changed
- Logged-in users are redirected away from logged-out pages (#499)

### Fixed
- Filtered item lists are ordered so pagination stays stable (#501)

### Under the hood
- mypy toolchain (#505); `signals.py` line endings normalized (#504)

## 2026-06-08

### Added
- Users can delete their account (#491)

### Changed
- UI/UX polish pass (#486)

## 2026-06-01

### Changed
- New design for the group approval toast message (#489)

### Fixed
- Toast messages now stack instead of overlapping (#488)

## 2026-05-25

### Added
- Workflow for nominating a new group moderator (#463)

### Fixed
- Memory use during image uploads (#487)

### Under the hood
- GitHub Actions CI (#480); a single icon library across the app (#485)

## 2026-05-18

### Changed
- Main navigation sections renamed because users found the old names confusing (#471)
- Bio removed from the registration form, and the explanation text updated (#473)
- After adding an item, users are redirected to a better page (#468)

### Fixed
- Available items can be deleted (#472)
- Group items were visible only to the group's creator (#467)

### Under the hood
- Agent guidelines (`AGENTS.md`) (#464); CI fixes (#481)

## 2026-05-11

### Added
- An indicator on groups with pending actions (#444)

### Fixed
- Orientation of uploaded images (#443)

### Under the hood
- `django-ipware`, to support stricter allauth checks (#466)

## 2026-05-04

### Fixed
- Group member counts include active members only and no longer overflow (#459)

## 2026-04-27

### Changed
- Your own items no longer appear in search results (#454)

### Under the hood
- Updated npm and Python dependencies (#456, #458)

## 2026-04-20

### Added
- Leave group button (#441)

### Changed
- Onboarding copy introduces Groups before Items (#453)
- The cancel notification request button is styled as a gray cancel button (#455)

### Under the hood
- Fixed migration collisions (#450, #451)

## 2026-04-13

### Added
- Banner upload on the group form (#448)

### Changed
- Different users can use the same group name (#404)

### Under the hood
- Missing lifecycle/audit fields added (#434); updated logo asset (#449)

## 2026-04-06

### Added
- Edit item screen (#410)
- QR codes for group invites (#431)

### Changed
- Updated the inventory page call to action (#411)
- Onboarding and landing page images optimized (#422)
- New default item card image (#432)
- Pending item banner icon changed to purple (#440)
- "About yourself" is limited to 200 characters (#425)

### Fixed
- Back button on the profile page (#413)
- Group trust icon; legacy group creators get moderator access again (#407, #408)
- Login code generation (#412)
- Text alignment, color and copy across group, item and form pages (#415, #418, #421, #423, #424, #426, #430, #433)

### Under the hood
- djlint reformat of all templates (#439); GitHub issue templates (#436)

## 2026-03-30

### Added
- Approval flow for group memberships (#369)
- Redesigned group detail page (#397)
- Empty state with a call to action on the groups page (#394)

### Changed
- UX audit fixes: button text, logo link, onboarding UI (#391)
- FAQ and external footer links open in a new tab (#398)
- Trust level is hidden from everyone except the item owner (#393)

### Fixed
- Duplicate borrow requests (#383)
- The name of a deleted group can be used again (#382)
- Item detail page fixes and return action visibility (#385, #401, #403, #405)

### Under the hood
- Search terms are stored for analytics (#384); djlint template formatting (#399)

## 2026-03-23

### Fixed
- "Notify when available": the database update is atomic, plus fixes and tests (#378)
- The "Standard" trust level wasn't displayed (#362)

## 2026-03-16

### Added
- "Notify me when available" for borrowed or reserved items (#349, #377)

### Changed
- Wording and visual consistency across pages and item forms (#372, #375)

### Fixed
- The group invite redirect is kept through login and onboarding (#363)
- Repositioning logic now works in Safari (#376)
- Privacy hardening (#373)

### Under the hood
- `.gitattributes` defaults (#364)

## 2026-03-09

### Changed
- Profile page enhancements (#326)
- New modals for creating and deleting items (#358)
- A login in progress can be cancelled, and post-login redirects were improved (#357)

### Fixed
- Item card styling (#344)
- Crash when a thumbnail file is missing (#361)

## 2026-03-02

### Added
- Redesigned item page (#323)

### Changed
- Updated inventory page (#281)
- New UX for login flows (#312, #325)
- Updated create group page (#316)

### Fixed
- Updating an item's category (#320)
- Duplicated paragraphs (#310)

## 2026-02-23

### Added
- Public profile page, as seen by other users (#295)
- Bio field on the signup form (#288)
- New item cards (#304)

### Changed
- Simpler trust levels (#302)

### Fixed
- Users who left a group could still see its items (#308)

## 2026-02-16

### Added
- Onboarding explanation screens (#282)

### Changed
- Updated group join UI (#267)
- The Log in / Sign up buttons moved out of the navbar (#278)

### Fixed
- The log out button did nothing (#291)
- Position of the "remove member" dropdown (#283)

## 2026-02-09

### Added
- Moderator filter on the group list, plus an improved group list UI (#284)

## 2026-01-26

### Changed
- New search flow UI, including creating an item from search (#241)

## 2026-01-19

### Added
- Users can delete their profile photo (#237)

### Changed
- Restyled the change password flow (#239)

### Fixed
- Permission checks added for every current object type (#234)
- Permission groups are linked by ID instead of name (#250, #251)

### Under the hood
- DaisyUI is bundled locally instead of loaded from a CDN (#240)

## 2026-01-12

### Under the hood
- Sentry error monitoring (#238)

## 2026-01-05

### Changed
- Text styling matches Figma (#236)

### Under the hood
- Updated onboarding docs for contributors (#203)

## 2025-12-29

### Added
- Group admins can remove members (#221)

### Changed
- Navbar menu items changed (#224)
- Avatar cards and notification alerts match Figma (#225, #235)
- The old single-category field on items was removed (#222)

## 2025-12-22

### Added
- Items can have multiple categories (#202)

### Changed
- Navbar and main profile page converted to DaisyUI (#187, #193)
- Updated UI for an empty inventory page (#226)

### Fixed
- The navbar shifted position (#194)

## 2025-12-08

### Added
- Search shows an empty state that encourages users to add items (#190)
- The group join page lists current members (#199)
- Group detail page shows the user's trust level, and the user can change it (#201)

### Changed
- Every view requires login (#195)
- Group invites carry through signup (#191)

### Under the hood
- Basic logging configuration (#198)

## 2025-11-24

### Changed
- The add photo button is hidden once an item has 5 photos (#179)
- Item photos are required (#183)

### Fixed
- Submit buttons are disabled after a click, to stop duplicate item creation (#185)

### Under the hood
- `django-imagekit` (#184); beta middleware is skipped when the beta is disabled (#186)

## 2025-11-17

### Changed
- Uploaded images are compressed: profile photos, item photos and group images (#166)
- Beta wall is off by default (#181)

### Fixed
- Users got an email notification about their own group join (#182)

## 2025-11-03

### Changed
- Search and Groups moved into the burger menu on mobile (#178)
- Group invite links no longer expire (#168)
- First and last name removed from Profile (#170)

## 2025-10-27

### Changed
- User profile split into two pages: Settings and Inventory (#165)
- Signup collects email and full name (#169)

## 2025-10-20

### Added
- Borrower agreement (#162)
- The beta wall can be turned off (#163)

### Fixed
- Submitting the add item form more than once uploaded duplicate images (#164)

## 2025-10-06

### Changed
- An item can't be requested while it has another pending request (#159)

### Under the hood
- `DJANGO_SETTINGS_MODULE` moved to platform environment variables (#160)

## 2025-09-29

### Changed
- New landing page content (#158)

## 2025-09-22

### Added
- Beta wall (#153)

### Changed
- Simpler footer (#154)
- The items list page is titled "Search" (#155)
- Group name and description limited to 50 and 500 characters (#156)

## 2025-09-08

### Changed
- Item descriptions can span multiple lines (#152)

## 2025-09-01

### Under the hood
- Fixed the test suite (#145)

## 2025-08-25

### Changed
- Basic approach to group permissions (#125)

## 2025-08-11

### Added
- Email notifications, plus UX improvements (#124)

### Under the hood
- Tools for loading demo data (#117)

## 2025-08-04

### Added
- Trust level setting on the item create/edit screen (#121)
- Plausible analytics (#123)

### Changed
- Profile "display name" replaced with first and last name (#122)

### Under the hood
- Cert (pre-prod) environment, and routes moved to the app subdomain (#115)

## 2025-07-28

### Changed
- Items list changes for the alpha (#118)

## 2025-07-21

### Changed
- Photos can be added in the item creation form (#113)
- After login, users land on the items page (#116)

## 2025-07-14

### Changed
- Redesigned borrowing flow UI on the item detail page (#106)
- Cleaned up the sign-in form (#114)

## 2025-07-07

### Changed
- Updated item grid styling (#89)
- Header is full width on every screen (#107)

### Under the hood
- Media stored on Wasabi S3 (#103); static files and Vite configured for production (#104)

## 2025-06-30

### Under the hood
- Prep work for group invite approvals (#71)
- Vite for hot module reloading and asset bundling (#75)

## 2025-06-09

### Added
- My Lends and My Borrows on the profile page (#86)

### Changed
- Branding updates to the navbar, footer, group pages, item detail and the profile item list (#83, #84, #85, #87, #88)
- The group listing shows the correct trust level (#93)

### Fixed
- Item permissions are removed from a group when the user leaves it (#91)

### Under the hood
- Production email proxy configured (#72)

## 2025-06-02

### Added
- Transactions can be cancelled (#70)

### Changed
- Updated profile page and group detail page UI (#69, #61)

### Under the hood
- Production hosting on platform.sh (#56)

## 2025-05-26

### Added
- Borrowing flows MVP: request, accept/reject and the UI around them (#51, #57)
- Group logo and banner images (#54)
- Items browser UI v1 (#55)

### Fixed
- Navigation buttons (#53)

## 2025-05-19

### Added
- Item photos (#47)

### Under the hood
- Base work for object-level permissions on groups (#43)

## 2025-05-12

### Added
- Item detail, create, edit, delete and list pages (#26)
- Join a group through an invite link (#28)
- Group creators automatically become moderators (#32)
- Basic navigation for Items and Groups (#37)
- Item search, filtered by permissions (#39, #42)
- Item visibility permissions (#20)

### Fixed
- Group template lookup (#23)

## 2025-05-05

### Added
- Groups and Items: initial create, read, update and delete (#4, #8, #18)
- Group permissions, part 1 (#11)
- Footer on every page (#7)

### Fixed
- Landing page alignment (#14)

### Under the hood
- Hot reload in development (#16)

## 2025-04-28

### Under the hood
- Templates reorganized at the top level (#2)

## 2025-04-21

### Under the hood
- Contributor docs (`CONTRIBUTING.md`) and data model diagram (DBML)

## 2025-04-14

### Added
- Project scaffold: Django, allauth login, user profiles, Tailwind styling
- First Item and ItemCategory models
- Landing page, rebuilt from the Softr MVP
