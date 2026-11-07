# Realtime Trains API: reference and findings

Researched 2026-11-07. The full OpenAPI spec is copied unchanged in `docs/rtt-openapi.yml` (MIT). This page is the
short version plus **what was actually observed**, which differs from the spec in places. Mark each claim's source:
**[spec]** the OpenAPI file, **[blog]** RTT's blog, **[observed]** a real response, **[others]** other projects' code
or docs, **[untested]** inferred but not yet seen.

## Status and cost

- The **old API (`api.rtt.io`, Basic auth, `/api/v1/json/search/...`) is gone.** It answered
  `418 I'm a Teapot: This API service is no longer available` on 2026-11-07 **[observed]**. It shut on 30 Sep 2026.
  `secure.realtimetrains.co.uk` shuts on 31 Mar 2027 **[blog]**. Most tutorials, libraries and answers online are for the
  dead API. Ignore anything using `serviceUid`/`runDate`/`locationDetail`.
- The **next-generation API** lives at `https://data.rtt.io`, launched March 2026 **[blog]**.
- **Free tier exists.** Sign up at `https://api-portal.rtt.io` with an RTT account. The limits are 10 a minute, 100 an hour and 1000 a day
  (cut in October 2026 from 30/750/9000) **[blog]**. Personal support is through RTT's Discord.
- **Paid (July 2026):** Hobbyist £4 a month (individuals) adds **detailed mode** and passenger allocations. Team £29 adds
  31-day history and 40/1200/12000. Professional £99 **[blog]**. We use the free tier. The owner said don't spend.
- **Terms:** the token must never be in a distributed user application. Apps must proxy through a server, or the
  token is revoked **[spec]**. Hence our server/PWA split.

## Auth

`Authorization: Bearer <token>`. You hold either a long-life **access token** or a long-life **refresh token**.
With a refresh token, call `GET /api/get_access_token` (bearer = refresh token) to get
`{token, entitlements[], validUntil}` **[spec]**. Without a token, every endpoint answers
`401 {"error":"Missing authorization token"}` **[observed]**.

`GET /api/info` returns `api_version`, and `credentials.{entitlements, historyRestriction, historyRestrictToDays,
namespaceRestriction, namespacesAvailable}` **[spec]**. Our client tries the token as an access token on `/api/info`,
and if that's refused, as a refresh token **[others: ha-realtime-trains does the same]**.

## Versioning, rate limits, errors

- A `Version: YYYY-MM-DD` header (or `?version=`) pins the API version. Otherwise you get the latest **[spec]**. We pin
  `2026-07-25`, the latest in the changelog.
- Every response has `X-RateLimit-Limit-{Minute,Hour,Day,Week}` and `X-RateLimit-Remaining-{...}`. Exceeding it gives
  `429` with `Retry-After` in seconds **[spec]**.
- Location search: `200`, `204` (no services, **no body**), `400`. Service: `200`, `404` **[spec]**. A history
  restriction gives a 400 for old dates **[others]**.

## Endpoints we use

### `GET /gb-nr/location`: departure/arrival board
| param | meaning |
|---|---|
| `code` (required) | any short (CRS, `RDG`) or long (TIPLOC, `RDNGSTN`) code |
| `filterFrom` / `filterTo` | only trains previously / subsequently calling at a code |
| `timeFrom` | ISO datetime. No offset means local time at the location. Defaults to now |
| `timeTo` *or* `timeWindow` | end of window (max 23 h 59 m), or window minutes (default 60). Not both |
| `timeTolerance` | nudges `timeFrom` earlier |
| `detailed` | detailed mode (paid). Ignored or limited on free |

Response: `systemStatus`, `query{location, timeFrom, timeTo, detailed}`, `services[]`. Each service is one row at
*this* location: `temporalData{arrival, departure, pass, scheduledCallType, realtimeCallType, displayAs, status,
isInterpolated}`, `locationMetadata{platform{planned, forecast, actual}, numberOfVehicles, allocationIndex, line, path}`,
`scheduleMetadata{uniqueIdentity, identity, departureDate, operator{code, name}, modeType, inPassengerService,
trainReportingIdentity}`, `origin[]`, `destination[]` (each `{location, temporalData}`), `reasons[]`.

There's no "departures only" flag. A board row with no `departure` is an arrival that terminates here. We filter.

### `GET /gb-nr/service`: one train's whole run
`uniqueIdentity=C05986:2026-09-06` (or `identity` + `departureDate`), plus `detailed`. Response `service{scheduleMetadata,
locations[], allocationData[], origin[], destination[], reasons[]}`. Each location has `location{description,
shortCodes[], longCodes[]}`, `temporalData`, `locationMetadata` (plus `allowances{engineering, pathing, performance}`
in **seconds**, on service queries only), and `associatedServices[]` (joins, divides, forms).

**Passing points:** a location whose `displayAs` is `PASS` *or null* is a pass, and its times are in `temporalData.pass`
**[spec, changelog 2026-04-17]**. `rail-announcements` (davwheat) maps null to PASS from the free API **[others]**, so passes
appear without detailed mode. Whether *every* timing point appears on free tokens is **[untested]**.

### `GET /data/stops`: passenger stops (version 2026-04-09+)
`{stops: [{namespace, description, shortCode, uniqueIdentity}]}`. Costs one call. We ship an offline station list instead
(see `src/realliferail/data/README.md`) and can refresh it from here when a token exists.

## Field semantics that matter

`IndividualTemporalData` (for each of arrival, departure and pass):
- `scheduleAdvertised` is the public timetable time (GBTT). `scheduleInternal` is the working timetable time (WTT), which can
  have half minutes and exists for passes. Detailed mode "enables internal times" **[spec]**, but the real non-detailed
  response included `scheduleInternal` anyway **[observed]**.
- `realtimeActual`: reported time. `realtimeForecast`: RTT's forecast. `realtimeEstimate`: RTT's own estimate when
  there was **no report** (entitlement `showEstimateTimeIfNoReport`). `realtimeNoReport: true` means the point was passed
  without a report.
- `realtimeInternalLateness` / `realtimeAdvertisedLateness`: whole minutes, only when an actual exists.
- `isCancelled`, `cancellationReasonCode`.

`displayAs`: `CALL`, `PASS` (or null), `CANCELLED`, `DIVERTED`, `STARTS`, `TERMINATES`. Origin and destination appear as
`CALL` **[changelog]**. `status` (live, at this location): `APPROACHING`, `ARRIVING`, `AT_PLATFORM`, `DEPART_PREPARING`,
`DEPART_READY` (signal off), `DEPARTING`. `isInterpolated`: RTT added this location itself.

`systemStatus.realtimeNetworkRail`: `OK` / `REALTIME_DATA_LIMITED` / `REALTIME_DATA_NONE`. `rttCore`: `OK` /
`REALTIME_DEGRADED` / `SCHEDULE_ONLY`. We show a banner when either isn't OK.

## Observed quirks (real board response, London Paddington, 2026-09-06, captured by another project)

1. Times have **no offset** (`"2026-09-06T14:51:00"`) and are UK local time. `query.timeFrom` *has* one
   (`+01:00`).
2. `query.location.longCodes` are namespaced (`"gb-nr:PADTON"`). Origin and destination long codes aren't (`"PADTON"`).
3. Origin and destination `location` carry only `description` and `longCodes`, with **no `shortCodes`**.
4. `platform.forecast` is populated (spec: "not currently used"). `platform.actual` appears once confirmed.
5. `scheduleMetadata.trainReportingIdentity` (headcode) was **absent** on that free board response. Don't rely on it.
6. `status: "APPROACHING"` appeared alongside an `arrival.realtimeActual`, so status can lag behind the actual.
7. `realtimeAdvertisedLateness` can be negative (-1, early against the public time while on time against the working timetable).
8. `query.detailed: false` is echoed back.

## What this API cannot give us

- **Signals and berths.** RTT builds passing points from Network Rail train describer (TD) berth steps internally
  **[others: railforums]**, but the API exposes only *timing points* (stations, junctions, named passes), not signals or
  berths. Signal-level positions need Network Rail's own open data TD feed (free with a Network Rail Open Data account,
  STOMP) and a berth-to-signal map. Recorded as a possible later stage in `docs/decisions.md`.
- **Coordinates.** No lat/lon. Stations come from our bundled list, and timing points have none.
- **Push.** Polling only.
- **Precision.** Actuals are whole minutes. Our position marker interpolates within the minute and says so.

## Allowance arithmetic (free tier)

100 an hour is the binding limit. One tracked train re-fetched every 30 s costs 120 an hour, which is too many. Every 60 s
costs 60 an hour, leaving 40 for boards. The budget therefore sets the service re-fetch interval to
`max(30 s, seconds_left_in_hour / (remaining_hour - reserve))`, with a reserve of 10 for searches. Board answers are cached for 60 s and
service answers for 30 s, shared by everyone using the server.
