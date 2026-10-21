# Load, reconnect and failure recovery

Owner: General CS, Phase 8. Code: `backend/scripts/loadtest/`.

This is the report on how the backend behaves with a full class connected,
when connections drop, and when the things it depends on fail. It has two
parts: what was tested and how, which is written by hand, and the results of
the latest run, which the test writes itself between the markers further down.

## What is tested

The test starts the backend as a process of its own, in production mode,
against a database it creates for the run and drops afterwards. It then drives
that server from outside, with one real WebSocket for each student and for the
lecturer's panel, and real HTTP requests for everything the lecturer does. So
what is exercised is what a deployment runs: stored users and consent, the
socket endpoint, the hub, the question cycle and the scheduler. Nothing in the
development database is read or written.

| Scenario | What happens | What has to hold |
|---|---|---|
| A class (`class`) | 40 students connect at once, and the lecturer sends questions which every student answers. | Everyone connects within 10 seconds and is counted once. Every answer is accepted, receipted and stored. Each question reaches the last student, and each receipt comes back, inside 2 seconds. No client sees a gap or a repeat in its stream. |
| Reconnect (`reconnect`) | Half the class loses its connection with no goodbye, misses a whole question and returns during the next. Then the whole class drops and returns at once. | Each client is resumed from the cursor it offers and is replayed exactly what it missed, the question and its close. The whole class is back inside 10 seconds and the panel's count returns to the class. A cursor from another stream is refused. |
| Signals and rooms (`signals`) | Every student confirms one of eight breakout rooms and sends attention signals four times a second for 16 seconds. The first four rooms talk, and the other four never do. In every room the odd-numbered students look away with no face in view. A question goes out in the middle of it. | The question still arrives on time, and no signal is refused or throttled with an error. The panel is told about every room. Rooms that talk are active, and silent ones need attention and raise one alert each. Nobody is sent a refocus prompt: everyone has answered every question, and by Cyber 1's rule the camera alone is no grounds for one. No student is sent a room's status or an alert. Engagement is reported for every student. A minute of attention reaches `attention_signal_summary` for every student. |
| Housekeeping (`housekeeping`) | A report is asked for twice while questions go out. The server runs the retention purge every few seconds. | The report is accepted at once, and the second request gets the same `report_id` back. Questions are not delayed. The report becomes ready, counts the questions delivered, and names no student. Its PDF downloads. The purge ran during the class, and every run gave way to it and deleted nothing. |
| Model down (`model`) | The tutor is asked questions with no model reachable. | Each gets a plain failure quickly. Questions still go out and are answered. Readiness reports the model as down. |
| Crash (`crash`) | The server process is killed with a question open, and started again. | Every client notices and reconnects. No cursor from before the crash is honoured. The session is active again with its count intact, the question that was open is not offered again, and an answer to it is refused with a receipt. The next question reaches everyone. |
| Planned restart (`restart`) | The server is asked to shut down, as a deploy does, and started again. | Every client is disconnected by the shutdown, and the class carries on after the restart. |
| Database outage (`database`) | The Postgres container is stopped for a few seconds and started again. Run only when asked for. | Liveness still answers and readiness says not ready. A delivery is refused with an error and does not hang. No socket is dropped, and a new connection is turned away to try again. With the database back, the class carries on. |
| Teams (`teams`) | A meeting is linked to a session and started and ended through the mock adapter, with the class waiting in it. | The meeting starting starts the session for everyone, the same event twice changes nothing, and the meeting ending ends it. A meeting with no session linked creates and starts one. The real adapter answers 503 with no Teams credentials. |
| Scheduler (`scheduler`) | Ten sessions run at once with the question cycle on, so the server sends every question itself on its own timers. | Every session keeps its cycle. No question is more than a second late. Every question closes with its whole class answered. |

If the server logs an error it did not expect during the run, the report gains
one more result, "Errors in" the log file, which fails and lists the first
lines. The class scenarios share one server and one class, and `class` always
runs when any scenario but `scheduler` is chosen, because the others happen to
that class.

### The signals and the purge in the test

Two of the checks depend on how the test server is configured, and the report
should be read with that in mind.

- **Signals.** The test server sets `REFOCUS_MIN_SIGNAL_SECONDS` to 10, and not
  the default of 45, so that 16 seconds of signals can be enough to prompt. A
  student's signals are accepted at most one every 2 seconds, so 16 seconds of
  them cover a little under 16. The socket limit
  (`ATTENTION_SIGNAL_MIN_INTERVAL_SECONDS`) is lowered to 0.2 seconds so that
  it does not interfere. Most of the signals sent are therefore dropped without
  any reply by the rule that holds a student to one signal every 2 seconds
  (see [signals-and-rooms.md](signals-and-rooms.md)), which is the situation the
  check is meant to be in. The minute check keeps every student sending a
  signal every few seconds, for up to 75 seconds, until a signal in the next
  clock minute has caused every student's minute to be stored, and then counts
  rows in `attention_signal_summary`.
- **The purge.** The test server sets `RETENTION_PURGE_INTERVAL_HOURS` to
  0.001, so the purge runs about every 4 seconds, and the first run is that
  soon after startup. The housekeeping check reads the server's log for
  `retention_purge` lines written while the class ran. With a class running,
  each line must say it deleted 0 items and stopped early. The check does not
  prove that the purge deletes anything. That is covered by
  `tests/test_purge_runner.py` and `tests/test_upload_purge.py`.

Two things are measured as times and not judged against a target, because the
project has not set one: how long a question takes to reach the last student,
and how long an answer takes to be receipted. Each has a limit of two seconds
in the checks, which is there to catch a system that has stopped working and
not one that is a little slow.

## How to run it

From `backend/`, with Postgres up:

```bash
python -m scripts.loadtest --out ../docs/load-test-results.json --markdown ../docs/load-and-recovery.md
```

| Option | Default | Meaning |
|---|---|---|
| `--students` | 40 | Students in the class. |
| `--rounds` | 8 | Questions in the first scenario. |
| `--classes` | 10 | Sessions in the scheduler scenario. |
| `--cycle-seconds` | 30 | How long the scheduler scenario runs. |
| `--only` | all | Scenario names, separated by commas. |
| `--database-outage` | off | Also stop and start the Postgres container. It serves the development database too, so nothing else can use it for those seconds. |
| `--database-container` | `clip-postgres` | The container to stop. |
| `--outage-seconds` | 8 | How long the database stays stopped. |
| `--database-host` | this machine's name | The host name the test server uses for the database. Production mode refuses `localhost`. |
| `--out`, `--markdown` | none | Where to write the results, as JSON and into this report. |

It exits with 0 when every check passed and 1 otherwise, prints a line for each
scenario, and says where it kept the server's log.

The server it starts has short timings so that a run is minutes and not hours:

| Setting | Test server | Why |
|---|---|---|
| `CHECKPOINT_RESPONSE_WINDOW_SECONDS` | 2 | A question closes quickly. |
| `CHECKPOINT_INTERVAL_MIN_SECONDS`, `CHECKPOINT_INTERVAL_MAX_SECONDS` | 0 | The question cycle is off, so the test sends each question itself. |
| `SIGNAL_WATCH_SECONDS` | 1 | The watch looks every second. |
| `ATTENTION_SIGNAL_MIN_INTERVAL_SECONDS` | 0.2 | See above. |
| `REFOCUS_MIN_SIGNAL_SECONDS` | 10 | See above. |
| `RETENTION_PURGE_INTERVAL_HOURS` | 0.001 | The purge runs every few seconds. |
| `ROOM_VOICE_FRESH_SECONDS` | 5 | A reading describes a member for five seconds. |
| `ROOM_QUIET_AFTER_SECONDS`, `ROOM_NEEDS_ATTENTION_AFTER_SECONDS` | 4 and 7 | A silent room needs attention after seven seconds. |

The scheduler scenario starts a second server with the cycle on: a question
every three seconds in every session, one second to answer and two between.
Nothing else about the server is changed.

## Results

<!-- results:begin -->

Run on 2026-10-21T12:57:10+00:00 at commit `40656c6e`, with 40 students.

- Machine: Windows-11-10.0.26300-SP0, 20 logical processors, Python 3.12.10.
- The backend, Postgres and all the clients ran on that one machine.
- **67 of 67 checks passed.**

| Scenario | Checks passed | Took |
|---|---|---|
| 40 students in one class, 8 questions | 9 of 9 | 17.9 s |
| Dropped connections, resumed | 9 of 9 | 7.5 s |
| Attention signals and breakout rooms under load | 11 of 11 | 18.2 s |
| Reports and the retention purge during a class | 9 of 9 | 6.1 s |
| The language model is unreachable | 3 of 3 | 19.0 s |
| The server is killed mid-question and restarted | 6 of 6 | 7.6 s |
| A planned shutdown and restart during a class | 2 of 2 | 7.3 s |
| The database is stopped for 8 s during a class | 7 of 7 | 37.7 s |
| A Teams meeting through the mock adapter | 7 of 7 | 2.3 s |
| 10 sessions at once on the automatic question cycle | 4 of 4 | 35.7 s |

### 40 students in one class, 8 questions

| Measured | Result |
|---|---|
| Connect all seconds | 1.38 |
| Time to ready | median 602.6 ms, 95th percentile 650 ms, worst 660.8 ms (40 samples) |
| Question fan out | median 21.9 ms, 95th percentile 37.8 ms, worst 38.8 ms (320 samples) |
| Of which server to student | median 1.1 ms, 95th percentile 2.7 ms, worst 2.7 ms (320 samples) |
| Of which the lecturers request | median 23.9 ms, 95th percentile 39.8 ms, worst 39.8 ms (8 samples) |
| Fan out first to last student | median 1.9 ms, 95th percentile 2.3 ms, worst 2.3 ms (8 samples) |
| Answer to receipt | median 15 ms, 95th percentile 24.3 ms, worst 48.7 ms (320 samples) |

| Check | Result |
|---|---|
| Every student connected and was told the session's state | passed |
| All connected inside 10 s | passed |
| The lecturer's panel counts every student once | passed |
| Every answer was accepted | passed |
| Every question closed with every student counted as shown and answered | passed |
| The slowest question reached its last student inside 2 s | passed |
| The slowest receipt came back inside 2 s | passed |
| Every answer is in the database | passed |
| No client saw a gap or a repeat in its stream | passed |

### Dropped connections, resumed

| Measured | Result |
|---|---|
| Half class resume seconds | 0.38 |
| Whole class reconnect seconds | 0.65 |
| Reconnect time to ready | median 474.4 ms, 95th percentile 575.8 ms, worst 623.5 ms (40 samples) |
| Fan out after reconnects | median 18.3 ms, 95th percentile 19.2 ms, worst 19.3 ms (40 samples) |

| Check | Result |
|---|---|
| Every returning student was resumed from the cursor it offered | passed |
| The question they missed was replayed to each, delivery and close | passed |
| The replay left no gap and repeated nothing | passed |
| Each could answer the question that was open when they came back | passed |
| That question closed with the whole class counted | passed |
| The whole class was back inside 10 s | passed |
| All were resumed from the cursor they offered, with no gap | passed |
| The panel's count returned to the whole class | passed |
| A cursor from another stream is refused, and the client starts afresh | passed |

### Attention signals and breakout rooms under load

| Measured | Result |
|---|---|
| Signals sent | 2450 |
| Signals per second | 153.1 |
| Fan out while signalling | median 18.6 ms, 95th percentile 19.3 ms, worst 19.4 ms (40 samples) |
| Room status events | 101 |
| Refocus prompts | 0 |
| Attention minutes stored | 40 |

| Check | Result |
|---|---|
| A question still reached everyone inside 2 s | passed |
| No signal was refused or throttled | passed |
| The panel was told about every room | passed |
| The rooms that talked are active | passed |
| The rooms that never talked came to need attention | passed |
| Each silent room raised one alert, and no other room did | passed |
| No student was sent a room's status or an alert | passed |
| Nobody who answers every question is prompted on the camera alone | passed |
| Engagement is reported for every student | passed |
| A minute of attention reached the analytics table for every student | passed |
| No gap in any stream | passed |

### Reports and the retention purge during a class

| Measured | Result |
|---|---|
| Fan out with reports building | median 21.9 ms, 95th percentile 28.8 ms, worst 29.2 ms (120 samples) |
| Fan out baseline | median 21.9 ms, 95th percentile 37.8 ms, worst 38.8 ms (320 samples) |
| Report pdf bytes | 3409 |
| Purge runs during class | 1 |

| Check | Result |
|---|---|
| The report was accepted at once | passed |
| Asking again while it is built returns the same report | passed |
| Questions still reached everyone inside 2 s | passed |
| The report became ready | passed |
| The report counts the questions delivered when it was asked for | passed |
| The report names no student | passed |
| The pdf downloads | passed |
| The purge ran while the class did | passed |
| Every purge during the class gave way to it and deleted nothing | passed |

### The language model is unreachable

| Measured | Result |
|---|---|
| Chat time to failure | median 5565 ms, 95th percentile 8083.7 ms, worst 8083.7 ms (4 samples) |
| Chat endings | error, error, error, error |
| Fan out with model down | median 25.8 ms, 95th percentile 26.6 ms, worst 26.8 ms (40 samples) |

| Check | Result |
|---|---|
| The tutor answered each question with a plain failure and no hang | passed |
| Questions still go out and are answered with the model down | passed |
| Readiness reports the model as down | passed |

### The server is killed mid-question and restarted

| Measured | Result |
|---|---|
| Clients noticed seconds | 0.05 |
| Restart to healthy seconds | 3.61 |
| Whole class back seconds | 0.88 |
| Fan out after restart | median 462.9 ms, 95th percentile 463.8 ms, worst 463.8 ms (40 samples) |
| Deliveries left unclosed by the crash | 1 |

| Check | Result |
|---|---|
| Every client noticed the connection had gone | passed |
| No cursor from before the crash was honoured | passed |
| The session came back active, with its count of questions intact | passed |
| The question that was open is not offered again | passed |
| An answer to the abandoned question is refused, with a receipt | passed |
| The next question reached and was answered by the whole class | passed |

Note: The question open at the crash has no recorded close. Readers treat a delivery whose closes_at has passed as closed by a restart, respondents unknown.

### A planned shutdown and restart during a class

| Measured | Result |
|---|---|
| Shutdown seconds | 0.39 |
| Close codes seen | 1012 |
| Restart to healthy seconds | 3.6 |
| Whole class back seconds | 0.87 |
| Fan out after restart | median 457.3 ms, 95th percentile 458.1 ms, worst 458.2 ms (40 samples) |

| Check | Result |
|---|---|
| Every client was disconnected by the shutdown | passed |
| The class carried on: the next question was answered by everyone | passed |

### The database is stopped for 8 s during a class

| Measured | Result |
|---|---|
| Readiness answered in seconds | 11.09 |
| Delivery refused in seconds | 10.37 |
| Ready again after seconds | 2.89 |
| Errors logged during outage | 3 |
| Fan out after recovery | median 72.7 ms, 95th percentile 73.4 ms, worst 73.4 ms (40 samples) |

| Check | Result |
|---|---|
| Readiness says the server is not ready | passed |
| Liveness still answers | passed |
| A delivery is refused with an error and not left hanging | passed |
| No socket was dropped while the database was away | passed |
| A new connection is turned away during the outage, to try again | passed |
| With the database back, a question reached and was answered by everyone | passed |
| No stream had a gap across the outage | passed |

### A Teams meeting through the mock adapter

| Measured | Result |
|---|---|
| Meeting start to last student | median 49.8 ms, 95th percentile 50.5 ms, worst 50.5 ms (40 samples) |

| Check | Result |
|---|---|
| The meeting was linked to a prepared session | passed |
| Students waiting in the meeting are told the session is prepared | passed |
| The meeting starting started the session for everyone | passed |
| The same event delivered twice changed nothing | passed |
| The meeting ending ended the session for everyone | passed |
| A meeting with no session linked creates and starts one | passed |
| The real teams adapter answers 503 while no teams credentials are set | passed |

### 10 sessions at once on the automatic question cycle

| Measured | Result |
|---|---|
| Questions per session | fewest 10, most 11 |
| Expected per session | about 10 |
| Seconds between questions | count 95, p50 3.01, max 3.05 |
| Seconds between questions expected | 3.0 |
| Worst lateness seconds | 0.05 |

| Check | Result |
|---|---|
| Every session kept its own cycle going | passed |
| No question was more than a second late | passed |
| Every question closed with its whole class answered | passed |
| No stream had a gap | passed |

<!-- results:end -->

## What the results say

These are the things worth knowing before a demo or a deployment. They follow
from how the system is built, and the tables above show whether the run bore
them out.

- **A question on a student's screen is one the database has.** The session row
  is locked, the question is claimed, and its delivery is recorded and
  committed before anyone is told. So a question is never missing from the
  session's history, and its close always has a row to complete. The cost is
  that the lecturer's request does the database work before it sends. The
  scenario reports the two parts separately: the lecturer's request, and the
  server's send to each student.
- **A dropped connection costs nothing that was sent.** A client that returns
  with its cursor is replayed what it missed, in order. The replay holds the
  last 128 events of each channel.
- **A restart loses the question that was open, and nothing else.** The
  session, its count of questions and every stored answer are in the database.
  The question that was open is not reopened, and its delivery has no recorded
  close. Anything that reads deliveries treats one whose `closes_at` has
  passed as closed by a restart, with its respondents unknown.
- **The cursor of a client that outlived a restart is refused.** A restarted
  server numbers its stream from one again. Each stream has an id that the
  client hands back, so an old cursor cannot be mistaken for a place in the new
  stream.
- **Rooms, signals and prompts are in memory.** After a restart a student is
  in no room until they confirm one again, and the rolling signal window starts
  empty. Attention minutes already stored in `attention_signal_summary` are
  kept, and the minute in progress at the time, at most 60 seconds, is lost.
- **The retention purge gives way to a class.** While any session is running
  it stops before deleting anything, and carries on in a later run once the
  class is over. A restart does not lose that work, because every task deletes
  oldest first.
- **The model being down does not touch a class.** The tutor reports a failure
  and the gateway stops trying for a while. Delivering a question does not call
  the model.
- **Readiness waits for the model.** `GET /api/v1/ready` asks the model server
  and waits up to 3 seconds for it. A load balancer that polls it should allow
  for that, or poll `GET /api/v1/health`.
- **Failing to reach something takes seconds on Windows.** With the database
  stopped, a request that needs it took about 10 seconds to fail, and
  readiness about 11. With the model unreachable, the tutor took 5 to 8
  seconds to report the failure. Neither is the server waiting: Windows
  retries a refused local connection for about two seconds a time before
  giving up, where Linux refuses at once. A deployment on Linux should fail
  these much faster; this run does not show it.
- **Only the requests that needed the database failed.** Three errors were
  logged while it was down, all from not reaching it, and none after. No socket
  was dropped, and the first question after it came back reached everyone.
- **One process.** Everything above is one backend process, which is how the
  application is meant to run: the hub, the classroom, the scheduler and the
  reports keep their state in it. How much of the machine a class uses was not
  measured.

## What is not tested here

- **Real networks.** Every client is on the same machine as the server, so
  latencies are the server's and not a campus network's. Lost packets and
  slow links are not simulated. A client that stops reading without closing
  is covered by the hub's own tests (`tests/test_hub_channels.py`), not here.
- **Real Teams.** The meeting scenario uses the mock adapter, which posts
  what the Teams bot would. The bot's own token checks have their own tests.
- **A real model.** The server is pointed at an address where nothing
  listens, so no model is loaded on the machine under test. The gateway's
  behaviour under a slow or failing model is covered by `tests/test_ai_gateway.py`.
- **Uploads.** Processing lecture material is not part of a live class and is
  not loaded here.
- **What the purge deletes.** The scenario checks only that the purge gives way
  to a class. Deleting is covered by the unit tests named above.
- **More than one class's worth.** Forty students in one session and forty
  across ten are what the project is sized for. The test takes `--students`
  and `--classes`, and nothing above is a claim about four hundred.
- **Browsers.** The clients speak the protocol the frontend speaks, and are
  not the frontend.
