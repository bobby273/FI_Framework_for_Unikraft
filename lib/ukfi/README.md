# ukfi — a fault injection framework for Unikraft

`ukfi` injects faults into Unikraft components at runtime and classifies what the
system does in response. It has two halves that can be used independently:

- **The injector** (`lib/ukfi/`) — an in-kernel library. You mark *injection
  sites* in the component you want to test with a macro; at boot, one site is
  armed from a kernel command-line parameter. One image serves an entire
  campaign: the site, the fault type and the trigger are all chosen at runtime.
- **The harness** (`lib/ukfi/harness/`) — host-side Python. It drives a
  campaign: builds the image once, runs the matrix of (site × fault ×
  trigger), collects signals from the guest log and from a workload client,
  classifies each run against a set of oracles, and writes one JSON line per run.

The two are decoupled. You can use the injector alone with a hand-written QEMU
command line, and you can point the harness at any component by editing a YAML
file — **no Python changes are required to target a different component.**

> This repository ships campaign descriptions for `lib9pfs` under two workloads
> as a worked example. They are examples, not part of the framework: targeting
> another component means writing a new `campaigns/*.yaml` and placing hooks in
> that component's source.

---

## Table of contents

- [Quick start](#quick-start)
- [Part 1 — The injector](#part-1--the-injector)
  - [Enabling the library](#enabling-the-library)
  - [Placing injection sites](#placing-injection-sites)
  - [Verifying that sites are linked in](#verifying-that-sites-are-linked-in)
  - [Fault types](#fault-types)
  - [Runtime parameters](#runtime-parameters)
  - [When does a fault fire?](#when-does-a-fault-fire)
  - [Build-time defaults](#build-time-defaults)
- [Part 2 — The harness](#part-2--the-harness)
  - [What one run does](#what-one-run-does)
  - [The campaign file](#the-campaign-file)
  - [Placeholders](#placeholders)
  - [Signals](#signals)
  - [Oracles](#oracles)
  - [Faults and admissible outcomes](#faults-and-admissible-outcomes)
  - [The matrix](#the-matrix)
  - [The protocol](#the-protocol)
  - [Running a campaign](#running-a-campaign)
  - [Inspecting the results](#inspecting-the-results)
- [Targeting a different component](#targeting-a-different-component)
- [Known constraints](#known-constraints)
- [Repository layout](#repository-layout)

---

## Quick start

Inject a single fault by hand, without the harness.

**1. Enable the library.** In your application's `.config`:

```
CONFIG_LIBUKFI=y
```

`LIBUKFI` selects `LIBUKDEBUG`, `LIBUKLIBPARAM`, `LIBUKSCHED`, `LIBUKPRINT`
and `LIBUKDEBUG_CRASH_SCREEN` on its own.

**2. Mark a site** in the component you want to test:

```c
#include <uk/fi.h>

int my_component_write(struct my_file *f, const void *buf, size_t len)
{
        UK_FI_SITE_ERR("write", -EIO);
        /* ... real work ... */
}
```

**3. Build, then arm the site from the command line:**

```
qemu-system-x86_64 -kernel build/myapp_qemu-x86_64 -nographic \
    -append "libukfi.fi_site=write libukfi.fi_fault=3 libukfi.fi_nop=5 -- <app args>"
```

This makes the 5th call to `my_component_write` return `-EIO`. The guest log
will contain:

```
Info: [libukfi] Fault injection site: libmycomp:write in file ... armed=1, inv=0, trigger.n_invocations=5
CRIT: [libukfi] Error fault injected at mycomp.c:42
```

Change `fi_fault` to 1, 2 or 4 to crash, hang or delay at the same point. The
image does not need rebuilding.

---

## Part 1 — The injector

### Enabling the library

```
menuconfig LIBUKFI   "ukfi: fault injection framework for Unikraft"
```

The library registers itself as `libukfi`, so **every runtime parameter is
prefixed `libukfi.`**. An unrecognised parameter is silently ignored by
`libukparam` — a typo in a parameter name does not produce an error, it
produces a run in which nothing is injected. Always confirm arming from the log
rather than from the command line you passed.

### Placing injection sites

Two macros, both from `<uk/fi.h>`. They differ in whether the site is allowed
to make the enclosing function return an error.

```c
UK_FI_SITE("name");             /* crash, hang and delay only */
UK_FI_SITE_ERR("name", err);    /* also: return (err) from the enclosing function */
```

Use `UK_FI_SITE_ERR` only where the function genuinely has a failure path —
where returning `err` is something a caller already has to handle. Use
`UK_FI_SITE` for functions that cannot fail (those that only ever return 0, or
return `void`). The distinction is recorded in the site descriptor as
`can_fail`, and the injector **refuses to arm** a `can_fail = 0` site with the
error fault, so a mis-declared site produces a run that never fires rather than
a bogus return value.

Both macros expand to a static descriptor placed in the `.uk_fitab` section
plus an inline counter increment. When the site is disarmed the cost is one
increment and one predicted-not-taken branch. When `CONFIG_LIBUKFI` is off,
both macros expand to nothing.

Three rules about names:

- **The name is the handle.** `fi_site=<name>` matches the string you pass to
  the macro, not the function or file name.
- **Names must be unique across the whole image.** Arming matches on the site
  name alone, *not* on `libname:site`. Two sites called `"write"` in different
  libraries will both be armed by `fi_site=write`. Prefix them if there is any
  chance of collision.
- **One site per source line.** The descriptor variable is named after
  `__LINE__`, so two macros on the same line collide at compile time.

Place the macro at the point where the fault should be observed, usually the
first statement of the function. Its line number is what the invocation counter
counts, which matters when you calibrate `fi_nop` (see
[Known constraints](#known-constraints)).

### Verifying that sites are linked in

A site that is compiled but not linked is invisible, and the symptom is a
campaign in which nothing ever fires. The section size is the check — each
descriptor is 64 bytes:

```
$ readelf -S build/myapp_qemu-x86_64 | grep -A1 uk_fitab
  [25] .uk_fitab  PROGBITS  ...  0000000000000280  ...
                             ^^^^^ 0x280 = 640 = 64 × 10 sites
```

The injector also prints every descriptor it finds at boot, one line each, with
`armed=0` or `armed=1`. That listing is the proof the hooks are in the image and that the selected one has been armed.

### Fault types

| `fi_fault` | name    | effect at the site | returns to caller? |
|-----------:|---------|--------------------|--------------------|
| 0 | none  | nothing | yes |
| 1 | crash | `UK_CRASH()` — crash screen, then platform termination | **no** |
| 2 | hang  | `while(1)` in the calling thread | **no** |
| 3 | error | the enclosing function returns the macro's `err` | returns `err` |
| 4 | delay | `uk_sched_thread_sleep()`, then normal execution | yes |

Notes that matter when you design a campaign:

- **crash** never returns. On x86 KVM it reaches the platform's crash path and
  terminates the guest; with `isa-debug-exit` wired up (see the `devices` key)
  that is a specific QEMU exit code.
- **hang** spins in the thread that hit the site. Other threads keep running, so
  the guest may stay partly responsive — this is a *component* hang, not a
  system freeze, and your oracles should expect that.
- **error** is the only fault that requires `UK_FI_SITE_ERR`. Requesting it on a
  plain site disarms the site and logs a warning.
- **delay** sleeps for a fixed 10 ms, compiled into `fi.c`. It is only compiled
  when `LIBUKSCHED` is on. A single 10 ms sleep is usually far below the noise
  of a benchmark's total duration, so observing a delay generally requires
  `fi_period` to make it fire repeatedly. Note also that the *nominal* 10 ms
  costs considerably more in practice because of scheduler tick granularity —
  measure it on your target before choosing a period.

### Runtime parameters

All are `libukfi.<name>=<value>` on the kernel command line, before the `--`
separator that ends kernel arguments.

| Parameter | Type | Meaning |
|-----------|------|---------|
| `fi_site`   | string | Name of the site to arm. Empty arms nothing. |
| `fi_fault`  | int    | Fault type, per the table above. |
| `fi_nop`    | uint   | Fire from the *n*-th invocation on. 0 is coerced to 1. |
| `fi_period` | uint   | 0 = fire once at `fi_nop`; *k* > 0 = fire every *k*-th invocation thereafter. |
| `fi_prob`   | uint   | Probability out of 100000. 100000 = always (and skips the RNG entirely). |
| `fi_seed`   | __u32  | Seed for the probabilistic trigger. 0 is coerced to 1. |

### When does a fault fire?

Exactly this condition, evaluated on every invocation of an armed site:

```
armed
  AND  inv >= fi_nop
  AND  (fi_period == 0  OR  (inv - fi_nop) % fi_period == 0)
  AND  (fi_prob == 100000  OR  rand() % 100000 < fi_prob)
```

Two consequences worth internalising:

- With `fi_period = 0` the fault fires on **every** invocation from `fi_nop`
  onwards, not only on the `fi_nop`-th one. For crash and hang this is
  indistinguishable from firing once; for error and delay it is not.
- `fi_nop` greater than the number of times the site is actually invoked
  produces a run in which the site is armed and nothing happens. The harness
  flags this (`fault_fired` is false) rather than silently recording it as a
  result.

The random state is currently shared by all sites and advances only when
`fi_prob < 100000`, so probabilistic runs are reproducible for a given seed as
long as exactly one site is armed.

### Build-time defaults

Every runtime parameter has a Kconfig counterpart used as its default:
`LIBUKFI_FI_SITE`, `_FI_NOP`, `_FI_PERIOD`, `_FI_PROB`, `_FI_SEED`,
`_FI_FAULT`. They are useful for a fixed reproduction case baked into an image.
For a campaign, leave them alone and drive everything from the command line.

`LIBUKFI_GCOV_AFTER_MS` is separate: when `LIBUKGCOV` is enabled it arms a timer
thread that requests shutdown after the given number of milliseconds, so a
long-lived server can produce a coverage dump and terminate cleanly. The harness
uses it as the run's time budget even when coverage is off — it is what makes an
unattended run end by itself.

---

## Part 2 — The harness

### What one run does

```
reset state  →  launch guest (QEMU)  →  wait for readiness  →  run client
          →  collect guest log and exit code  →  evaluate signals
          →  classify against oracles  →  append one JSON line
```

Every step is described by the campaign YAML. The runner contains no knowledge
of any particular component, application or protocol beyond two built-in
metrics parsers.

### The campaign file

One YAML file per campaign, in `harness/campaigns/`. Eleven top-level keys.

```yaml
name: "mycomp"          # free-form label
timeout: 40             # hard per-run deadline in seconds
active: true

build:
  defconfig: "mycomp-0.21"   # a file in lib/ukfi/defconfigs/ that should be created before the campaign as you would normally on Unikraft
  jobs: 4

run:
  app_dir: "/path/to/app"               # make is invoked here
  kernel: "workdir/build/app_qemu-x86_64"
  qemu: "qemu-system-x86_64"
  memory: "256M"
  accel: "kvm"
  port: 6379                            # guest-side service port
  hostfwd: "tcp::6379-:6379"
  rootfs: "rootfs"                      # 9pfs share, relative to app_dir
  mount_tag: "fs0"
  devices: ["-device isa-debug-exit,iobase=0x501,iosize=2"]
  exit_codes:                           # QEMU exit code → meaning
    83: "clear_shutdown"
    85: "crash"
    0:  "acpi_fallback"
  reset: ["rm -rf <rootfs>/state"]      # shell, run before every run
  append:
    baseline: "libukfi.gcov_after_ms=<ms> -- /app.conf"
    injected: "libukfi.fi_site=<site> libukfi.fi_fault=<fault> libukfi.fi_nop=<nop> libukfi.fi_period=<period> libukfi.gcov_after_ms=<ms> -- /app.conf"
  gcov_after_ms: 25000                  # the guest's self-shutdown deadline
  log: "boot.log"

workload:
  readiness:
    command: "mycli -h 127.0.0.1 -p <port> ping"
    expect: "PONG"            # substring that must appear in stdout
    interval_ms: 200
    deadline_s: 20
    on_failure: "guest_never_ready"
  client:
    command: "mybench -h 127.0.0.1 -p <port> -n 10000"
    duration_s: 0.9           # expected duration, for reference
  metrics: ["throughput_rps", "latency_max_ms", "latency_p99_ms"]
  metrics_parser: "redis_benchmark"     # or "apache_bench"
  degraded_if:
    duration_factor: 1.5      # slower than 1.5 × baseline ⇒ client_degraded
  teardown: ["pkill -f mybench"]

signals:   {...}   # see below
oracles:   [...]   # see below
faults:    {...}   # see below
matrix:    {...}   # see below
protocol:  {...}   # see below
```

### Placeholders

Any `<token>` in `reset`, `append`, `readiness.command` or `client.command` is
substituted before use. The runner raises if a `<` survives substitution, so a
typo fails loudly on the first run instead of producing an odd command line.

| Token | Source |
|-------|--------|
| `<ms>` | `run.gcov_after_ms` |
| `<rootfs>` | `run.app_dir` + `/` + `run.rootfs` |
| `<port>` | `run.port` |
| `<host_port>` | `run.host_port` |
| `<site>` | current run's site (injected runs only) |
| `<fault>` | `faults.<name>.fi_fault` of the current run |
| `<nop>` | current run's `fi_nop` |
| `<period>` | current run's period |

### Signals

A signal is a named boolean computed once per run. Each declares a `source` and,
for some sources, a `kind`. These are the combinations the runner implements:

| source | kind | true when |
|--------|------|-----------|
| `guest_log` | *(none)* | `pattern` appears in the log window |
| `guest_log` | `log_order` | `pattern` appears **before** `before` |
| `runner` | `timeout` | the run hit `timeout` |
| `client` | `nonzero_exit` | the client exited non-zero |
| `client` | `nonzero_exit_or_bad_responses` | as above, or the parsed metrics report failed responses |
| `client` | `readiness_failed` | the readiness probe never succeeded |
| `client` | `duration_factor` | client duration > `degraded_if.duration_factor` × baseline |
| `config` | *(none)* | this run requested a fault |

Add a signal by adding a block to the YAML; the runner dispatches on
`(source, kind)`, not on the signal's name, so no code changes are needed as
long as you reuse an existing combination.

> **The log window.** Guest-log patterns are searched in the log *truncated at
> the clean-shutdown marker*, not in the whole log. This exists because the
> shutdown path of a given configuration may itself end in a crash screen if
> it does, an untruncated search makes "it crashed" true on every run, including
> baselines -for example, we forced Redis and Nginx to shutdown since they don't
> terminate on their own-. Set `clear_shutdown` to a marker your guest prints when 
> it begins shutting down, and verify on a known-good run that your baselines
> classify cleanly before trusting anything else.

### Oracles

An ordered list. Each entry has a `name` and any combination of `all_of`,
`none_of` and `any_of` over signal names. **The first matching rule wins**, so
order in the file is semantics: put specific rules above general ones and a
catch-all last.

```yaml
oracles:
  - name: "gold_run"
    all_of: ["clear_shutdown"]
    none_of: ["crash_screen", "guest_timeout", "client_error", "fault_fired"]
  - name: "crash_error_run"
    all_of: ["fault_fired", "crash_screen", "client_error"]
    none_of: ["clear_shutdown"]
  # ...
  - name: "unclassified_run"      # catch-all
```

Oracles see only signals. They do not know which fault was requested, which is
what makes them an independent oracle: a run classified as `delay_run` while
`error` was injected is a finding, not a misclassification.

### Faults and admissible outcomes

```yaml
faults:
  error:
    fi_fault: 3
    requires_can_fail: true     # skip this fault on sites that cannot fail
    must_fire: true             # fault_fired must be true, or the run is broken
    admissible: ["fail_silent_run", "api_error_run", "crash_error_run"]
  delay:
    fi_fault: 4
    fi_period_override: 10      # overrides matrix.fi_period for this fault only
    must_fire: true
    admissible: ["delay_run", "fail_silent_run"]
```

`must_fire` is a *mechanical invariant*, not an expected result: if the fault
did not fire, the run is not evidence of anything. `admissible` is a **set**,
deliberately — declaring a single expected outcome would turn the most
interesting result (fault injected, nobody noticed) into an anomaly to explain
away.

### The matrix

```yaml
matrix:
  sites:
    write:  { can_fail: true,  fi_nop: [1, 250, 400] }
    close:  { can_fail: false, fi_nop: [1, 2, 4] }
  faults: [crash, hang, error, delay]
  fi_period: 0
  fi_prob: 100000
  baseline_runs: 5
```

`can_fail` here must agree with the macro you used at the site. Where it is
false, the `error` fault is skipped for that site.

The `fi_nop` values are the one part of the matrix that cannot be guessed: they
must come from measuring how many times each site is actually invoked under your
workload. `harness/profiles/` holds the coverage-based scripts used for that —
and the [Known constraints](#known-constraints) section explains why those
counts are an upper bound.

A useful convention: the lowest value targets the boot phase, the highest
targets steady-state service. On the same site this distinguishes "the
application does not start" from "the application degrades while serving".

### The protocol

```yaml
protocol:
  rounds: 2                     # every configuration is run this many times
  repeat: "all"
  baseline:
    count: 5
    interleave_every: 20        # a baseline every N injected runs
  results: "results/mycomp.jsonl"
  append_immediately: true      # one line flushed per run; safe to kill
  resume_from: "last_row"       # restart skips rows already present
  abort_if:
    consecutive_must_fire_failures: 3
    consecutive_infra_errors: 3
  infra_retry: 1
```

Two rounds of the *same* configuration, paired by `id`, is what lets you report
reproducibility: agreement means reproducible, disagreement is a third category
rather than a measurement error. Interleaved baselines detect machine drift
during the campaign instead of leaving you to infer it afterwards. The abort
rule exists because an unattended campaign in which nothing ever fires is not a
result — it is a systematic error, and it should stop early.

### Running a campaign

```sh
cd lib/ukfi/harness

python3 runner.py mycomp.yaml          # one campaign, both rounds
bash campagna.sh                       # orchestration: warm-up + all campaigns
PASSATE=2 bash campagna.sh             # repeat the whole protocol twice
```

`campagna.sh` adds what an unattended run needs: a discarded warm-up boot (the
first run of a campaign pays a cold page cache and can be an order of magnitude
slower, which would corrupt the baseline), a refusal to start if the machine is
too slow, a per-campaign time cap, and cleanup of stray QEMU processes between
campaigns.

To run it detached:

```sh
nohup bash campagna.sh > /dev/null 2>&1 &
tail -f results/campagna-*.log
```

### Inspecting the results

Each run appends one JSON object to the results file, with the run's identity
(`id`, `site`, `fault`, `nop`, `period`, `kind`, `round`), every signal, the raw
observations (`ready_ms`, `duration_s`, `qemu_exit`, `timed_out`), the parsed
metrics, and the classification (`outcome`, `oracle`). Per-run guest logs are
kept at `<app_dir>/logs/<id>-r<round>.log`.

Two scripts read that file, and they answer different questions:

```sh
python3 verifica.py results/mycomp.jsonl [expected_row_count]
python3 analysis.py results/mycomp.jsonl [more.jsonl ...]
```

- **`verifica.py` — did the chain work?** Row count, required fields, every
  injected run actually fired, baselines all classified clean, nothing in the
  catch-all. It judges the *apparatus*, not the results. Run it first; if it
  fails, the numbers mean nothing no matter how plausible they look.
- **`analysis.py` — what do the results say?** Outcome distribution, the
  fault × observed-class matrix, outcomes per site, non-firing site/`fi_nop`
  pairs, round-to-round reproducibility, a cross-workload comparison, and the
  split of crash screens by cause (which opens each run's log). Output is
  Markdown tables on stdout.

---

## Targeting a different component

Nothing in the injector or the runner is specific to any component. Targeting a
new one is a YAML file plus hooks:

**1. Place the hooks.** Add `UK_FI_SITE` / `UK_FI_SITE_ERR` to the functions you
want to test, in that component's source. Choose `UK_FI_SITE_ERR` only where the
function has a real failure path, and give each site a name unique across the
image.

**2. Check they are in the image.** `readelf -S | grep uk_fitab` — the section
should be 64 bytes per site — and confirm the boot-time listing names all of
them.

**3. Measure invocation counts.** Run your workload with coverage on and read
the execution count *of the exact hook line*. This is what sets the `fi_nop`
values, and guessing them wastes whole runs.

**4. Write `campaigns/<name>.yaml`.** The sections that always need rewriting:

- `run` — paths, QEMU flags, the two `append` templates, the guest's
  exit-code mapping, what `reset` must delete between runs.
- `workload` — the readiness probe and its expected substring, the client
  command, which metrics parser to use.
- `signals` — at minimum, update `clear_shutdown` and `fault_in_boot` to
  markers *your* application prints. The patterns are application-specific even
  though the signal names are not.
- `matrix` — your sites, their `can_fail`, and the measured `fi_nop` values.
- `oracles` — reusable almost verbatim if your signal names match, since they
  are expressed over signals only.

**5. Gate before you commit to a full campaign.** Derive a cut-down campaign —
one site, all four faults, two baselines — and run it. `campaigns/prova.yaml.gen.py`
shows the pattern: it generates the reduced file *from* the real one, so the
signals, oracles and protocol cannot drift apart from what you will actually
run. A twelve-run gate takes minutes and catches the class of defect that would
otherwise produce a full campaign of confidently wrong data.

**6. Add a metrics parser only if you need one.** The runner ships parsers for
`redis-benchmark` and `apache_bench`. A different client means a new branch in
`parse_metrics()` — this is the one place where a new component or workload may
require touching Python.

---

## Known constraints

These are properties of the approach, discovered by running it. They generalise
beyond any particular component.

**Coverage-based invocation counts are an upper bound.** If your coverage dump
writes through the component you are measuring — a filesystem, a block device,
a network stack — then the dump's own I/O is counted in the numbers you are
calibrating against. Sites the dump exercises will be overestimated by a fixed
number of operations. The error is additive, so it is negligible on a site
invoked thousands of times and decisive on one invoked seven times. Treat the
profile as a ceiling and verify with a short run that your highest `fi_nop`
actually fires.

**A clean shutdown may itself crash.** In some configurations the teardown path
ends in a kernel assertion, producing a crash screen on *every* run including
baselines. This is why the log window exists. Before trusting any
classification, confirm that your baselines come out clean.

**Timing signals are only as good as your baseline's dispersion.** A fault whose
effect is smaller than the run-to-run variance of your workload cannot be
classified reliably, and a single campaign may show an apparent effect that a
second campaign does not reproduce. If you report a performance-based outcome,
report the baseline spread next to it, and prefer repeating the campaign over
tightening the threshold.

**QEMU with `-nographic` reads stdin.** Launched in a background process group
with stdin still attached to a terminal, it receives `SIGTTIN` and is suspended
— the guest appears to crawl rather than to fail, which is easy to misdiagnose
as a slow machine. Always redirect stdin from `/dev/null`.

**`$(PWD)` in an application Makefile is the environment variable**, not the
working directory, and `subprocess.run(cwd=...)` does not update it. The runner
sets it explicitly when invoking the build.

**Current limitations, in order of how likely they are to bite:**

- `parse_metrics()` has two built-in parsers; a third client needs code.
- `analysis.py` resolves per-run logs through a hard-coded application root.
- The delay fault's sleep is a compile-time constant in `fi.c`.
- The probabilistic trigger shares one RNG state across all sites, so
  `fi_prob < 100000` is only reproducible with a single site armed.
- Arming matches on the site name alone, not on `library:site`.

---

## Repository layout

```
lib/ukfi/
├── fi.c  fi.ld                  the injector; six runtime parameters
├── include/uk/fi.h              the public API: UK_FI_SITE, UK_FI_SITE_ERR
├── gcov.c  gcov_glibc_shim.c    coverage dump for long-lived guests
├── exportsyms.uk                symbols kept visible to instrumented libraries
├── defconfigs/                  per-application build configurations
└── harness/
    ├── campaigns/               one YAML per campaign, plus the reduced-gate generator
    ├── profiles/                invocation-count measurement scripts
    ├── samples/                 captured logs and client output, to test oracles offline
    ├── results/                 one .jsonl per campaign
    ├── runner.py                executes a campaign
    ├── verifica.py              mechanical checks on a .jsonl
    ├── analysis.py              result tables from one or more .jsonl
    └── campagna.sh              unattended orchestration
```

`samples/` is worth knowing about: it holds real captured output, so the log
window, the metrics parsers and the whole oracle set can be exercised without
booting a guest — a half-second test cycle instead of a thirty-second one.

---

## References

The experiment design follows two papers:

- Cotroneo, De Simone, Liguori, Natella, Bidokhti, *How Bad Can a Bug Get?*,
  ESEC/FSE 2019 — four-category failure taxonomy, fault-independent oracle,
  coverage-guided injection.
- Wada & Yamada, *Reboot-Based Recovery of Unikernels at the Component Level*,
  DSN 2024 — fail-stop fault model and component-level operation list.
