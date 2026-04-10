# Testing HomeSecure with test-homesecure.py

`test-homesecure.py` is an end-to-end test suite that talks directly to the
HomeSecure container API. It runs against a live container — either a local
Docker container started from `build-local.sh`, or the real add-on running
inside Home Assistant.

No third-party packages are required. It uses only Python's standard library.

---

## Contents

- [Prerequisites](#prerequisites)
- [Finding Your PINs](#finding-your-pins)
- [Running the Tests](#running-the-tests)
  - [Quick smoke test — no credentials](#1-quick-smoke-test--no-credentials)
  - [Full read-only test](#2-full-read-only-test)
  - [Full test suite with write operations](#3-full-test-suite-with-write-operations)
  - [Full test suite including arm/disarm](#4-full-test-suite-including-armdisarm)
  - [Testing with a token-protected container](#5-testing-with-a-token-protected-container)
  - [Testing against the live add-on in HA](#6-testing-against-the-live-add-on-in-ha)
  - [Running only specific test groups](#7-running-only-specific-test-groups)
- [Understanding the Output](#understanding-the-output)
- [Test Groups Reference](#test-groups-reference)
- [What Each Test Actually Does](#what-each-test-actually-does)
- [Interpreting Failures](#interpreting-failures)
- [CI / Automated Use](#ci--automated-use)

---

## Prerequisites

**Python 3.8 or later.** Check with:

```bash
python3 --version
```

**A running HomeSecure container.** Either:

- The local Docker container started by `build-local.sh` (listening on
  `localhost:18099`), or
- The real add-on running in Home Assistant (listening on `localhost:8099`
  from HA's perspective, or at your HA host IP from another machine).

---

## Finding Your PINs

The test script needs two PINs for its full test suite. You'll know one of
them already. The other is generated automatically on first boot.

### Admin PIN

This is the PIN you set when you added your first admin user in the admin
panel. If you're testing against a fresh container with no users yet, you'll
need to create one first — either through the Lovelace admin card, or
directly via the API:

```bash
# Create the first admin user on a fresh container
# (no admin_pin required when the user table is empty)
curl -s -X POST http://localhost:8099/api/users \
  -H "Content-Type: application/json" \
  -d '{"name":"Admin","pin":"123456","is_admin":true,"admin_pin":""}' \
  | python3 -m json.tool
```

### Service PIN

The service PIN is auto-generated on first container startup and stored in
the database. It's printed in the container log every time the container
starts. Find it like this:

**If using the local Docker container from build-local.sh:**
```bash
docker logs homesecure-smoke-test 2>&1 | grep -i "service pin"
```

**If running the add-on in Home Assistant:**
1. Go to **Settings** → **Add-ons** → **HomeSecure**
2. Click the **Log** tab
3. Search for `service pin` or `SERVICE_PIN`

The line will look something like:
```
[INFO] Service PIN: 87654321
```

The service PIN can be used to arm and disarm — it's intended for the HA
integration's `alarm_control_panel` entity and for testing. Any valid user
PIN also works for disarming once the system is armed.

---

## Running the Tests

All examples below assume the container is running on `localhost:8099`.
Adjust the `--url` flag if your setup differs.

---

### 1. Quick smoke test — no credentials

Checks that the container is up and the core read-only endpoints are
responding. Safe to run at any time, against any environment.

```bash
python3 test-homesecure.py
```

This runs: `health`, `state`, `config`, `zones`, `locks`, `logs`,
and `bad_auth`. Write tests and arm/disarm are skipped with a warning.

Expected output when everything is healthy:
```
HomeSecure v2.0 — API Test Suite
Target : http://localhost:8099
Token  : none
Groups : all

Checking connectivity...
  ✓ Container reachable (HTTP 200)

──────────────────────────────────────────────────
  Health Check
──────────────────────────────────────────────────
  ✓ GET /health → HTTP 200
  ✓ health status: status='ok'

──────────────────────────────────────────────────
  Alarm State
──────────────────────────────────────────────────
  ✓ GET /api/state → HTTP 200
  ✓ alarm state: state='disarmed'
  ✓ State 'disarmed' is a valid alarm state
...
  ⚠ --admin-pin not provided — skipping write tests
  ⚠ --service-pin not provided — skipping arm/disarm test

══════════════════════════════════════════════════
Results: 14/14 passed, 4 skipped
══════════════════════════════════════════════════
```

---

### 2. Full read-only test

Same as above but explicitly confirms auth rejection works — requires no
real credentials because it tests with a deliberately wrong PIN.

```bash
python3 test-homesecure.py --url http://localhost:8099
```

Output is the same as above. The `bad_auth` group always runs and uses
`000000` as the wrong PIN, expecting a `401` or `403` response.

---

### 3. Full test suite with write operations

Adds user creation, update, enable/disable toggle, and deletion.
**This creates a real user in the database and then deletes it as cleanup.**
Safe to run against a live system — the test user (`Test User CI`) is
always cleaned up at the end even if intermediate tests fail.

```bash
python3 test-homesecure.py --admin-pin 123456
```

Replace `123456` with your actual admin PIN.

The `users` and `user_toggle` test groups are now active:

```
──────────────────────────────────────────────────
  User Management
──────────────────────────────────────────────────
  ✓ GET /api/users → HTTP 200
  ✓ users list: users=[...]
  ✓ POST /api/users (create) → HTTP 200
  ✓ Created user id=7
  ✓ PUT /api/users/7 → HTTP 200
  ✓ User update verified: name='Test User CI Updated'

──────────────────────────────────────────────────
  User Enable/Disable
──────────────────────────────────────────────────
  ✓ PUT /api/users/7 (disable) → HTTP 200
  ✓ User successfully disabled
  ✓ PUT /api/users/7 (re-enable) → HTTP 200

──────────────────────────────────────────────────
  User Deletion (cleanup)
──────────────────────────────────────────────────
  ✓ DELETE /api/users/7 → HTTP 200
  ✓ User confirmed deleted from list
```

---

### 4. Full test suite including arm/disarm

Adds a live arm/disarm cycle. **This will actually arm your alarm system
for a few seconds.** Only run this when you are physically present and able
to disarm if something goes wrong, or against a test container with no real
sensors attached.

```bash
python3 test-homesecure.py \
  --admin-pin 123456 \
  --service-pin 87654321
```

The `arm_disarm` test group:
1. Confirms the system starts in `disarmed` state (skips entirely if not)
2. Arms home via `POST /api/arm_home`
3. Waits 1 second, then confirms state is `armed_home` or `arming`
4. Disarms via `POST /api/disarm`
5. Waits 1 second, then confirms state is back to `disarmed`
6. Tries to disarm with PIN `000000` and confirms it gets a `400`/`401`/`403`

```
──────────────────────────────────────────────────
  Arm / Disarm
──────────────────────────────────────────────────
  ✓ POST /api/arm_home → HTTP 200
  ✓ System armed (state='armed_home')
  ✓ POST /api/disarm → HTTP 200
  ✓ System disarmed successfully
  ✓ Wrong PIN correctly rejected (HTTP 400)
```

> **Note:** The test arms in `home` mode, not `away`, because `away` starts
> an exit delay timer and the state check immediately after arming would see
> `arming` rather than `armed_away`. Both are handled correctly — the test
> accepts either `armed_home` or `arming` as a valid post-arm state.

---

### 5. Testing with a token-protected container

If you set `api_token` in the add-on config, all endpoints (except
`POST /api/zones/trigger`) require a Bearer token. Pass it with `--token`:

```bash
python3 test-homesecure.py \
  --token mytoken \
  --admin-pin 123456 \
  --service-pin 87654321
```

When `--token` is provided, the `bad_auth` group also runs an extra check:
it makes a request **without** the token and confirms the server returns
`401`. This verifies that token protection is actually active.

```
──────────────────────────────────────────────────
  Auth Rejection
──────────────────────────────────────────────────
  ✓ Bad admin PIN correctly rejected on POST /api/users (HTTP 401)
  ✓ Missing token correctly rejected (HTTP 401)
```

---

### 6. Testing against the live add-on in HA

If you want to test the real running add-on rather than a local Docker
container, point `--url` at your HA host. The add-on listens on port 8099.

**From the same machine as HA:**
```bash
python3 test-homesecure.py \
  --url http://localhost:8099 \
  --admin-pin 123456
```

**From another machine on your network:**
```bash
python3 test-homesecure.py \
  --url http://192.168.1.100:8099 \
  --admin-pin 123456
```

Replace `192.168.1.100` with your HA host's IP address.

> **Warning:** Running the full suite including `--service-pin` against the
> live add-on will briefly arm your real alarm system. Make sure you're home
> and ready before doing this.

---

### 7. Running only specific test groups

Use `--only` with a comma-separated list of group names to run a subset of
tests. Useful when debugging a specific area without running the full suite.

```bash
# Just the health check
python3 test-homesecure.py --only health

# Health and state only
python3 test-homesecure.py --only health,state

# Only the user management tests
python3 test-homesecure.py --only users,user_toggle,delete_user \
  --admin-pin 123456

# Only arm/disarm
python3 test-homesecure.py --only arm_disarm \
  --admin-pin 123456 \
  --service-pin 87654321
```

All available group names are listed in the
[Test Groups Reference](#test-groups-reference) below.

---

## Understanding the Output

Each line starts with one of four symbols:

| Symbol | Colour | Meaning |
|--------|--------|---------|
| `✓` | Green | Test passed |
| `✗` | Red | Test failed |
| `⚠` | Yellow | Warning — not a failure, but worth attention |
| `→` | Blue | Informational — no pass/fail judgement |

Warnings (`⚠`) are used for things like "found 0 locks" — the API responded
correctly but there's nothing to inspect. They don't increment the failure
counter.

Informational lines (`→`) report counts or values without asserting anything
— for example, how many events are in the log.

The summary line at the end:
```
Results: 18/22 passed, 4 skipped
```
means 18 assertions passed, 4 were skipped (because `--admin-pin` or
`--service-pin` wasn't provided), and 0 failed. The script exits with code
`0` on success and `1` if any test fails.

---

## Test Groups Reference

| Group name | Flag required | What it tests |
|------------|--------------|---------------|
| `health` | none | `GET /health` — container up, Z-Wave status |
| `state` | none | `GET /api/state` — valid alarm state returned |
| `config` | none | `GET /api/config` — delay fields present |
| `zones` | none | `GET /api/zones` — endpoint responds, shape is correct |
| `locks` | none | `GET /api/locks` — endpoint responds (0 locks is OK) |
| `logs` | none | `GET /api/logs` — endpoint responds |
| `bad_auth` | none | Wrong PIN and (if `--token` set) missing token both rejected |
| `users` | `--admin-pin` | List, create, and update a test user |
| `user_toggle` | `--admin-pin` | Disable and re-enable the test user created by `users` |
| `arm_disarm` | `--service-pin` | Arm home, verify state, disarm, verify state, test wrong PIN |
| `delete_user` | `--admin-pin` | Delete the test user created by `users` (cleanup) |

---

## What Each Test Actually Does

### `health`
Calls `GET /health`. Checks HTTP 200 and that the response contains a
`status` field. The value of `zwave_connected` is reported but not asserted
— it will be `false` in a local test environment without a real Z-Wave JS
server, and that's expected.

### `state`
Calls `GET /api/state`. Checks HTTP 200, that a `state` field is present,
and that its value is one of the six known alarm states: `disarmed`,
`arming`, `armed_home`, `armed_away`, `pending`, or `triggered`.

### `config`
Calls `GET /api/config`. Checks HTTP 200 and that `entry_delay`,
`exit_delay`, and `alarm_duration` are all present. These are the three
fields most likely to break if the database schema or defaults change.

### `zones`
Calls `GET /api/zones`. Checks HTTP 200. If zones exist, verifies the first
one has an `entity_id` field. Reports the count informally. An empty list is
not a failure — a fresh container has no zones configured.

### `locks`
Calls `GET /api/locks`. Checks HTTP 200. Reports the lock count. Zero locks
is expected in any environment without a real Z-Wave JS connection.

### `logs`
Calls `GET /api/logs?limit=10`. Checks HTTP 200. Reports how many events
are in the log. Zero events is expected on a fresh database.

### `bad_auth`
Posts to `POST /api/users` with `admin_pin: "000000"` and expects a `401`
or `403`. If `--token` was provided, also makes a token-free request to
`GET /api/users` and expects a `401` or `403`.

### `users`
1. Calls `GET /api/users` — checks the list endpoint works
2. Calls `POST /api/users` with a test user named `"Test User CI"` and PIN
   `777888` — checks HTTP 201 and that an `id` is returned
3. Calls `PUT /api/users/{id}` to rename the user to `"Test User CI Updated"`
   and add a phone number
4. Calls `GET /api/users` again and verifies the name change is reflected

The created user ID is passed to `user_toggle` and `delete_user` so they
operate on the same test user.

### `user_toggle`
1. Calls `PUT /api/users/{id}` with `enabled: false` — disables the test user
2. Calls `GET /api/users` and verifies `enabled` is `0` for that user
3. Calls `PUT /api/users/{id}` with `enabled: true` — re-enables the user

### `arm_disarm`
1. Calls `GET /api/state` and skips entirely if not `disarmed`
2. Calls `POST /api/arm_home` with `--service-pin`
3. Waits 1 second
4. Calls `GET /api/state` and checks for `armed_home` or `arming`
5. Calls `POST /api/disarm` with `--service-pin`
6. Waits 1 second
7. Calls `GET /api/state` and checks for `disarmed`
8. Calls `POST /api/disarm` with PIN `000000` and checks for `400`/`401`/`403`

### `delete_user`
Calls `DELETE /api/users/{id}` on the test user created by `users`, then
calls `GET /api/users` and verifies the user is no longer in the list.

---

## Interpreting Failures

### `ConnectionError: Cannot connect to container`
The container isn't running or the URL is wrong. Check:
- `docker ps` to verify the container is running
- That the port matches (`8099` for the add-on, `18099` for the local
  smoke test container from `build-local.sh`)
- That no firewall is blocking the port

### `GET /health → expected HTTP 200, got 500`
The container started but something crashed. Check the container logs:
```bash
docker logs <container_id>
```

### `POST /api/users (create) → expected HTTP 200, got 403`
The `--admin-pin` you provided is wrong, or there are no admin users in the
database yet. Verify the PIN by logging into the admin card in Lovelace, or
create an initial admin user manually via curl (see
[Finding Your PINs](#finding-your-pins)).

### `POST /api/arm_home → expected HTTP 200, got 400`
The system is already armed, or the service PIN is wrong. Check:
```bash
curl -s http://localhost:8099/api/state | python3 -m json.tool
```
If the state is not `disarmed`, disarm it first before running the
arm/disarm test group.

### `Wrong PIN correctly rejected` shows a warning instead of a pass
The server returned a status code other than `400`, `401`, or `403` for a
wrong PIN. This likely means the disarm endpoint is not validating PINs
properly. Check the coordinator's `disarm()` method.

### `User update not reflected in user list`
The `PUT` returned 200 but the subsequent `GET /api/users` doesn't show the
change. This is a database commit issue — check whether `update_user()` in
`database.py` is calling `conn.commit()`.

### `Missing token correctly rejected` shows a warning
`--token` was passed but the server accepted the token-free request anyway.
This means the `api_token` option in the add-on config is not set or not
being read from the environment variable `HOMESECURE_API_TOKEN`. Verify
`run.sh` is exporting it correctly.

---

## CI / Automated Use

The script exits with code `0` on full pass and `1` if any test fails,
making it suitable for a CI pipeline. Skipped tests do not cause a non-zero
exit.

Example GitHub Actions step, assuming the container is started as a service
before the test step:

```yaml
- name: Run HomeSecure API tests
  run: |
    python3 test-homesecure.py \
      --url http://localhost:8099 \
      --admin-pin ${{ secrets.HS_ADMIN_PIN }} \
      --service-pin ${{ secrets.HS_SERVICE_PIN }}
```

For CI environments where you want to skip arm/disarm (no real alarm system):

```yaml
- name: Run HomeSecure API tests (no arm/disarm)
  run: |
    python3 test-homesecure.py \
      --url http://localhost:8099 \
      --admin-pin ${{ secrets.HS_ADMIN_PIN }} \
      --only health,state,config,zones,locks,logs,bad_auth,users,user_toggle,delete_user
```
