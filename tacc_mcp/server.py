#!/usr/bin/env python3
import subprocess
import os
import re
import shlex
import shutil
from fastmcp import FastMCP

mcp = FastMCP(name="tacc-slurm")

# ── cluster registry ───────────────────────────────────────
# Add new clusters here — no code changes needed elsewhere
CLUSTERS = {
    "ls6": {
        "ssh_alias":   os.environ.get("LS6_SSH_ALIAS",    "ls6"),
        "scratch_dir": os.environ.get("LS6_SCRATCH_DIR",  "/scratch/<system-id>/<username>/"),
        "desc":        "Lonestar6",
    },
    "sp3": {
        "ssh_alias":   os.environ.get("S3_SSH_ALIAS",     "sp3"),
        "scratch_dir": os.environ.get("S3_SCRATCH_DIR",   "/scratch/<system-id>/<username>/"),
        "desc":        "Stampede3",
    },
}
DEFAULT_CLUSTER = os.environ.get("TACC_DEFAULT_CLUSTER", "ls6")
# ──────────────────────────────────────────────────────────


def _get_cluster(cluster: str | None) -> tuple[dict, str] | tuple[None, str]:
    """Resolve cluster name, return (config, error_or_none)."""
    name = (cluster or DEFAULT_CLUSTER).lower()
    if name not in CLUSTERS:
        valid = ", ".join(CLUSTERS.keys())
        return None, f"Unknown cluster '{name}'. Valid options: {valid}"
    return CLUSTERS[name], None


def _rsync_bin() -> str:
    """Resolve a working GNU rsync, avoiding macOS's openrsync (protocol 29),
    which segfaults against TACC's rsync. Override with TACC_RSYNC_BIN.
    Falls back to plain 'rsync' if nothing better is found."""
    if env := os.environ.get("TACC_RSYNC_BIN"):
        return env
    candidates = [
        "/opt/homebrew/bin/rsync",   # Homebrew (Apple Silicon)
        "/usr/local/bin/rsync",      # Homebrew (Intel) / manual install
        shutil.which("rsync"),
    ]
    for c in candidates:
        if not c or not os.path.exists(c):
            continue
        try:
            v = subprocess.run([c, "--version"], capture_output=True, text=True)
            if "openrsync" not in (v.stdout + v.stderr).lower():
                return c            # a real GNU rsync
        except Exception:
            continue
    return "rsync"                  # last resort (may be openrsync)


# LS6's own /etc/profile.d/z90_login_modules.sh calls an undefined DBG_ECHO and
# writes this to stderr on every login shell. Pure noise; filtered so it cannot be
# mistaken for a tool's error output.
_BENIGN_STDERR = ("DBG_ECHO: command not found",)


def _ssh(alias: str, cmd: str, login: bool = True) -> tuple[str, str, int]:
    """Run `cmd` on `alias`.

    login=True wraps it in `bash -lc` so /etc/profile.d is sourced. This is not
    cosmetic: $WORK, $WORK2 and $SCRATCH are set ONLY by a login shell, and TACC's
    server-side job_submit.lua plugin (slurm.conf: JobSubmitPlugins=lua) aborts
    any submission whose environment cannot resolve them --
    "Unable to query WORK2 environment variable...(job submission aborted)".
    A non-login shell therefore cannot submit a job at all, nor even probe the
    queue with `sbatch --test-only`, which goes through the same validation.

    shlex.quote is what makes this safe: ssh hands the string to the remote login
    shell, which unwraps exactly one level of quoting before bash -lc sees it.
    """
    remote = f"bash -lc {shlex.quote(cmd)}" if login else cmd
    result = subprocess.run(
        ["ssh", alias, remote],
        capture_output=True, text=True
    )
    stderr = "\n".join(
        line for line in result.stderr.splitlines()
        if not any(b in line for b in _BENIGN_STDERR)
    )
    return result.stdout.strip(), stderr.strip(), result.returncode


def _check_socket(alias: str) -> str | None:
    r = subprocess.run(
        ["ssh", "-O", "check", alias],
        capture_output=True, text=True
    )
    if r.returncode != 0:
        return (
            f"SSH ControlMaster socket for '{alias}' is not active. "
            f"Run `ssh {alias}` in a terminal to authenticate (2FA), then retry."
        )
    return None


# ── tools ──────────────────────────────────────────────────

@mcp.tool
def list_clusters() -> str:
    """List available TACC clusters and their descriptions."""
    lines = [f"Default cluster: {DEFAULT_CLUSTER}\n"]
    for name, cfg in CLUSTERS.items():
        lines.append(f"  {name:10} {cfg['desc']}  →  ssh alias: {cfg['ssh_alias']}")
    return "\n".join(lines)


@mcp.tool
def check_connection(cluster: str | None = None) -> str:
    """Check SSH ControlMaster socket for a cluster (default: ls6)."""
    cfg, err = _get_cluster(cluster)
    if err:
        return err
    socket_err = _check_socket(cfg["ssh_alias"])
    if socket_err:
        return f"❌ {socket_err}"
    return f"✅ SSH socket active for {cfg['desc']} ({cfg['ssh_alias']})"


@mcp.tool
def upload_files(local_dir: str, remote_subdir: str,
                 cluster: str | None = None) -> str:
    """
    Rsync a local directory to a cluster's scratch space.
    cluster: 'ls6' or 's3' (default: ls6)
    """
    cfg, err = _get_cluster(cluster)
    if err:
        return err
    if socket_err := _check_socket(cfg["ssh_alias"]):
        return f"❌ {socket_err}"

    remote = f"{cfg['scratch_dir']}/{remote_subdir}"
    # Ensure the remote parent path exists (rsync only creates the final leaf,
    # and the old TACC receiver predates --mkpath).
    _, mkderr, mkrc = _ssh(cfg["ssh_alias"], f"mkdir -p '{remote}'")
    if mkrc != 0:
        return f"❌ could not create remote dir {remote}:\n{mkderr}"
    r = subprocess.run(
        [_rsync_bin(), "-avz", "--exclude=__pycache__", "--exclude=*.pyc",
         f"{local_dir}/", f"{cfg['ssh_alias']}:{remote}/"],
        capture_output=True, text=True
    )
    if r.returncode != 0:
        return f"❌ rsync failed:\n{r.stderr}"
    return f"✅ {local_dir} → {cfg['ssh_alias']}:{remote}"


# ── queue probing ──────────────────────────────────────────
# Validation patterns. Every field is checked HERE and the remote argv is built
# only from values that passed, which is what makes single-quoting them safe.
_RE_WORD = re.compile(r"^[A-Za-z0-9._-]+$")
_RE_TIME = re.compile(r"^([0-9]+-)?[0-9]{1,3}(:[0-9]{2}){0,2}$")

# `--test-only` and `--wrap=hostname` are literals below with no code path that
# omits them, so "probe the queue" cannot become "submit a job".
_PROBE_PREAMBLE = r"""
NOW=$(date +%s)
ROW=0
RAW=""

fmt_wait() {
    s=$1
    [ "$s" -lt 0 ] && s=0
    if [ "$s" -eq 0 ]; then echo "immediate"; return; fi
    d=$(( s / 86400 )); h=$(( (s % 86400) / 3600 )); m=$(( (s % 3600) / 60 ))
    if   [ "$d" -gt 0 ]; then printf '%dd %dh %dm' "$d" "$h" "$m"
    elif [ "$h" -gt 0 ]; then printf '%dh %dm' "$h" "$m"
    else                      printf '%dm' "$m"
    fi
}

probe() {
    P="$1"; NN="$2"; TT="$3"; NT="$4"; NC="$5"
    ROW=$(( ROW + 1 ))
    set -- --test-only -p "$P" -N "$NN" -t "$TT" --wrap=hostname
    [ -n "$NT" ]   && set -- "$@" -n "$NT"
    [ -n "$NC" ]   && set -- "$@" -c "$NC"
    [ -n "$ACCT" ] && set -- "$@" -A "$ACCT"

    # LS6 banners every submission: a welcome block, "No reservation for this
    # job", then a dozen "--> Verifying ...OK" lines. Strip those first, or a
    # plain tail reports banner text as if slurm had said it.
    OUT=$(sbatch "$@" 2>&1 |
          grep -vE '^-->|^-+$|Welcome to|^No reservation|^[[:space:]]*$')
    VERDICT=$(printf '%s\n' "$OUT" | grep -iE '^sbatch:|allocation failure|error')
    [ -n "$VERDICT" ] && OUT="$VERDICT"
    OUT=$(printf '%s\n' "$OUT" | tail -n 2)
    RAW="${RAW}${ROW}  ${OUT}
"
    TS=$(printf '%s' "$OUT" | grep -oE 'to start at [0-9T:-]+' | awk '{print $4}' | head -1)
    if [ -n "$TS" ] && SE=$(date -d "$TS" +%s 2>/dev/null); then
        START=$(date -d "$TS" '+%Y-%m-%d %H:%M')
        WAIT=$(fmt_wait $(( SE - NOW )))
    else
        START="—"; WAIT="**rejected**"
    fi
    printf '| %d | %s | %s | %s | %s | %s | %s | %s |\n' \
        "$ROW" "$P" "$NN" "${NT:-—}" "${NC:-—}" "$TT" "$START" "$WAIT"
}

echo "# queue-wait probe — $(hostname -s) — $(date '+%Y-%m-%d %H:%M:%S %Z')"
if [ -n "$ACCT" ]; then echo "# account: $ACCT"; else echo "# account: (default)"; fi
echo "# every probe is 'sbatch --test-only'; nothing was submitted"
echo
echo "| # | queue | -N | -n | -c | walltime | est. start | est. wait |"
echo "|--:|-------|---:|---:|---:|----------|------------|-----------|"
"""

_PROBE_EPILOGUE = r"""
echo
echo "## Raw scheduler messages"
echo '```'
printf '%s' "$RAW"
echo '```'
echo
echo "## Live caps (qlimits)"
echo '```'
qlimits 2>&1 | grep -vE '^-->|^-+$|Welcome to|^No reservation' | head -40
echo '```'
"""


@mcp.tool
def estimate_start(configs: list[dict], account: str | None = None,
                   cluster: str | None = None) -> str:
    """Ask the scheduler when each of several HYPOTHETICAL jobs would start.
    Submits nothing -- every probe is `sbatch --test-only`.

    PASS EVERY SHAPE YOU WANT COMPARED IN ONE CALL. All of them are probed in a
    single ssh round trip, ~0.14 s apart, because comparing them is the whole
    point and the queue moves while you probe. Calling this once per shape gives
    you snapshots taken at different moments, which are not comparable.
    Parallelism belongs ACROSS clusters (ls6 vs sp3 cannot share a connection),
    never across shapes.

    configs: list of dicts, each with
        partition      (required) e.g. "normal", "development", "gpu-a100"
        nodes          (required) int, SLURM -N
        walltime       (required) "MM:SS" | "HH:MM:SS" | "D-HH:MM:SS"
        ntasks         (optional) int, SLURM -n
        cpus_per_task  (optional) int, SLURM -c
    account: allocation to charge (e.g. "<ALLOCATION>"). Priority is per-allocation,
        so an estimate without one may not match the job you actually submit.

    Returns the per-shape table, the raw scheduler messages, and live `qlimits`.

    A row reading **rejected** means the scheduler declined that shape. If EVERY
    row is rejected, suspect the site rather than the shapes -- a submit filter
    aborts identically for every size -- and treat it as `probe unavailable`,
    i.e. an absence of information, not a per-shape verdict.
    """
    cfg, err = _get_cluster(cluster)
    if err:
        return err
    if socket_err := _check_socket(cfg["ssh_alias"]):
        return f"❌ {socket_err}"

    if not configs:
        return "❌ no configurations to probe: `configs` is empty."
    if account is not None and not _RE_WORD.match(account):
        return f"❌ bad account '{account}'"

    calls = []
    for i, c in enumerate(configs, 1):
        if not isinstance(c, dict):
            return f"❌ config {i}: expected an object, got {type(c).__name__}"
        part = str(c.get("partition", "")).strip()
        walltime = str(c.get("walltime", "")).strip()
        nodes = c.get("nodes")
        if not part or nodes is None or not walltime:
            return (f"❌ config {i}: 'partition', 'nodes' and 'walltime' are all "
                    f"required. Ask rather than guess a node count or walltime — "
                    f"an invented one gives a confident number for a job nobody "
                    f"intends to run.")
        if not _RE_WORD.match(part):
            return f"❌ config {i}: bad partition '{part}'"
        if not _RE_TIME.match(walltime):
            return (f"❌ config {i}: bad walltime '{walltime}' — expected "
                    f"MM:SS, HH:MM:SS or D-HH:MM:SS")

        ints = {}
        for key in ("nodes", "ntasks", "cpus_per_task"):
            val = c.get(key)
            if val is None or val == "":
                ints[key] = ""
                continue
            try:
                n = int(val)
            except (TypeError, ValueError):
                return f"❌ config {i}: '{key}' must be an integer, got {val!r}"
            if n <= 0:
                return f"❌ config {i}: '{key}' must be positive, got {n}"
            ints[key] = str(n)
        if not ints["nodes"]:
            return f"❌ config {i}: 'nodes' is required"

        calls.append("probe '{}' '{}' '{}' '{}' '{}'\n".format(
            part, ints["nodes"], walltime, ints["ntasks"], ints["cpus_per_task"]))

    script = (f"ACCT={shlex.quote(account or '')}\n"
              + _PROBE_PREAMBLE + "".join(calls) + _PROBE_EPILOGUE)

    stdout, stderr, rc = _ssh(cfg["ssh_alias"], script)
    if rc != 0 and not stdout:
        return f"❌ probe could not run on {cfg['desc']}:\n{stderr}"

    note = ("\n_Snapshot from a single round trip. The queue moves — compare these "
            "rows against each other, never against a number from an earlier "
            "session. qlimits reports node/wall/job caps only; charge rates are "
            "not in it._")
    if stdout.count("**rejected**") == len(configs):
        note = ("\n⚠  **probe unavailable** — every shape was rejected, which is "
                "one site-level cause, not " f"{len(configs)} per-shape verdicts. "
                "The ssh worked and the script ran; the scheduler declined to "
                "answer. See the raw messages above for why. Size from "
                "`reference/taccLS6-nodes.md` and mark the estimate `unprobed`." + note)
    return f"[{cfg['desc']}] {stdout}\n{note}"


@mcp.tool
def submit_job(remote_subdir: str, slurm_script: str = "job.slurm",
               cluster: str | None = None) -> str:
    """
    Submit a SLURM job. Returns job ID on success.
    cluster: 'ls6' or 's3' (default: ls6)
    """
    cfg, err = _get_cluster(cluster)
    if err:
        return err
    if socket_err := _check_socket(cfg["ssh_alias"]):
        return f"❌ {socket_err}"

    remote = f"{cfg['scratch_dir']}/{remote_subdir}"
    stdout, stderr, rc = _ssh(
        cfg["ssh_alias"],
        f"cd {remote} && sbatch {slurm_script}"
    )
    if rc != 0:
        return f"❌ sbatch failed on {cfg['desc']}:\n{stdout}\n{stderr}".strip()

    # LS6 wraps every submission in a banner -- a welcome block, "No reservation
    # for this job", then a dozen "--> Verifying ...OK" lines -- so the job id has
    # to be extracted rather than assumed to be the whole of stdout.
    m = re.search(r"Submitted batch job (\d+)", stdout)
    if not m:
        return (f"❌ sbatch returned no job id on {cfg['desc']}:\n"
                f"{stdout}\n{stderr}".strip())
    return f"✅ [{cfg['desc']}] Submitted batch job {m.group(1)}"


@mcp.tool
def job_status(job_id: str, cluster: str | None = None) -> str:
    """Get current status of a SLURM job."""
    cfg, err = _get_cluster(cluster)
    if err:
        return err
    if socket_err := _check_socket(cfg["ssh_alias"]):
        return f"❌ {socket_err}"

    stdout, _, _ = _ssh(
        cfg["ssh_alias"],
        f"squeue -j {job_id} -h -o '%T %R' 2>/dev/null"
    )
    if stdout:
        return f"[{cfg['desc']}] Job {job_id}: {stdout}"
    stdout, _, _ = _ssh(
        cfg["ssh_alias"],
        f"sacct -j {job_id} -o JobID,State,ExitCode,Elapsed -n | head -2"
    )
    return (
        f"[{cfg['desc']}] Job {job_id} (completed):\n{stdout}"
        if stdout else
        f"Job {job_id} not found on {cfg['desc']}"
    )


@mcp.tool
def list_my_jobs(cluster: str | None = None) -> str:
    """List your queued/running jobs on a cluster, or all clusters if cluster='all'."""
    if cluster == "all":
        results = []
        for name, cfg in CLUSTERS.items():
            if err := _check_socket(cfg["ssh_alias"]):
                results.append(f"[{name}] ⚠️  socket dead")
                continue
            stdout, _, _ = _ssh(cfg["ssh_alias"], "squeue --me -h -o '%.10i %.12j %.8T %R'")
            results.append(f"── {cfg['desc']} ──\n{stdout or 'no jobs'}")
        return "\n\n".join(results)

    cfg, err = _get_cluster(cluster)
    if err:
        return err
    if socket_err := _check_socket(cfg["ssh_alias"]):
        return f"❌ {socket_err}"
    stdout, _, _ = _ssh(
        cfg["ssh_alias"],
        "squeue --me -o '%.10i %.12j %.8T %.12M %.12l %R'"
    )
    return f"[{cfg['desc']}]\n{stdout}" if stdout else "No jobs in queue."


@mcp.tool
def get_log(job_id: str = "", lines: int = 80, cluster: str | None = None,
            log_path: str | None = None) -> str:
    """
    Fetch the tail of a SLURM job's stdout and stderr logs.

    If log_path is given, tail that file directly (absolute path, or relative
    to the cluster's scratch dir). Otherwise resolve StdOut/StdErr from job_id.
    """
    cfg, err = _get_cluster(cluster)
    if err:
        return err
    if socket_err := _check_socket(cfg["ssh_alias"]):
        return f"❌ {socket_err}"

    alias = cfg["ssh_alias"]

    # Direct-path mode: skip resolution, just tail what the user named
    if log_path:
        path = log_path if log_path.startswith("/") else f"{cfg['scratch_dir']}/{log_path}"
        content, stderr, rc = _ssh(alias, f"tail -n {lines} {path} 2>&1")
        if rc != 0:
            return f"❌ Could not read {path}:\n{content or stderr}"
        return f"── {path} ──\n{content or '(empty)'}"

    if not job_id:
        return "❌ Must provide either job_id or log_path"

    # 1. scontrol resolves StdOut/StdErr for running and recently-completed jobs
    info, _, _ = _ssh(alias, f"scontrol show job {job_id} -o 2>/dev/null")
    out_path = err_path = workdir = None
    for tok in info.split():
        if tok.startswith("StdOut="):
            out_path = tok[len("StdOut="):]
        elif tok.startswith("StdErr="):
            err_path = tok[len("StdErr="):]
        elif tok.startswith("WorkDir="):
            workdir = tok[len("WorkDir="):]

    # 2. For older jobs scontrol forgets — sacct still has the workdir
    if not workdir:
        wd, _, _ = _ssh(
            alias,
            f"sacct -j {job_id} -o WorkDir%500 -P -n 2>/dev/null | head -1"
        )
        workdir = wd.strip() or None

    # 3. Glob the workdir (or scratch root) for *{job_id}*.{out,err}
    if not out_path or not err_path:
        search_root = workdir or cfg["scratch_dir"]
        if not out_path:
            g, _, _ = _ssh(
                alias,
                f"find {search_root} -maxdepth 4 -name '*{job_id}*.out' 2>/dev/null | head -1"
            )
            out_path = g or None
        if not err_path:
            g, _, _ = _ssh(
                alias,
                f"find {search_root} -maxdepth 4 -name '*{job_id}*.err' 2>/dev/null | head -1"
            )
            err_path = g or None

    if not out_path and not err_path:
        return f"No log found for job {job_id} on {cfg['desc']}"

    sections = []
    for label, path in [("STDOUT", out_path), ("STDERR", err_path)]:
        if not path:
            sections.append(f"── {label}: (not found) ──")
            continue
        content, _, _ = _ssh(alias, f"tail -n {lines} {path} 2>/dev/null")
        sections.append(f"── {label}: {path} ──\n{content or '(empty)'}")
    return "\n\n".join(sections)


@mcp.tool
def cancel_job(job_id: str, cluster: str | None = None) -> str:
    """Cancel a SLURM job."""
    cfg, err = _get_cluster(cluster)
    if err:
        return err
    if socket_err := _check_socket(cfg["ssh_alias"]):
        return f"❌ {socket_err}"
    _, stderr, rc = _ssh(cfg["ssh_alias"], f"scancel {job_id}")
    return f"✅ Cancelled {job_id} on {cfg['desc']}" if rc == 0 else f"❌ {stderr}"


@mcp.tool
def run_remote_command(command: str, cluster: str | None = None) -> str:
    """
    Run an arbitrary command on a cluster's login node.
    For environment checks, quick tests, module inspection etc.
    Not for long-running work — use submit_job for that.
    """
    cfg, err = _get_cluster(cluster)
    if err:
        return err
    if socket_err := _check_socket(cfg["ssh_alias"]):
        return f"❌ {socket_err}"

    stdout, stderr, rc = _ssh(cfg["ssh_alias"], command)
    out = stdout
    if stderr:
        out += f"\n[stderr]: {stderr}"
    if rc != 0:
        out += f"\n[exit: {rc}]"
    return out or "(no output)"


@mcp.tool
def fetch_results(remote_subdir: str, local_output_dir: str,
                  cluster: str | None = None,
                  include: list[str] | None = None) -> str:
    """Download results from a cluster's scratch to a local directory.

    include: filenames to fetch, e.g. ["FORCE_CONSTANTS", "SPOSCAR"]. Given, they
    become an rsync allowlist and NOTHING else transfers -- which also means
    subdirectories are not entered, so a displacement farm's 300 task dirs stay
    on the cluster. Omitted, the whole directory comes down; that is how 309 MB
    of WAVECAR and 5 licence-restricted POTCARs ended up in this repo, so the
    result line always reports what was actually transferred.

    POTCAR never transfers in either direction: it is licence-restricted and is
    assembled on the cluster by the vasp skill's generate_POTCAR.sh.
    """
    cfg, err = _get_cluster(cluster)
    if err:
        return err
    if socket_err := _check_socket(cfg["ssh_alias"]):
        return f"❌ {socket_err}"

    if include and any(os.path.basename(f) == "POTCAR" for f in include):
        return ("❌ POTCAR is licence-restricted and is never fetched. It is "
                "assembled on the cluster by generate_POTCAR.sh; verify it there "
                "with `grep -c '^ *TITEL' POTCAR`.")

    remote = f"{cfg['scratch_dir']}/{remote_subdir}"
    os.makedirs(local_output_dir, exist_ok=True)

    # -L dereferences symlinks. Without it rsync copies the LINK, and a link
    # pointing at an absolute remote path dangles the moment it lands here --
    # the file looks present and cannot be opened.
    args = [_rsync_bin(), "-avzL", "--exclude=POTCAR"]
    if include:
        # First match wins in rsync, so the excludes above already stand. The
        # trailing --exclude=* is what makes this an allowlist AND what stops
        # recursion into task subdirectories.
        args += [f"--include={f}" for f in include] + ["--exclude=*"]
    args += [f"{cfg['ssh_alias']}:{remote}/", f"{local_output_dir}/"]

    r = subprocess.run(args, capture_output=True, text=True)
    if r.returncode != 0:
        return f"❌ rsync failed:\n{r.stderr}"

    # Report what actually landed. A silent whole-directory pull is the failure
    # mode this tool had; making its size visible is the cheapest guard.
    n_files = total = 0
    for root, _dirs, files in os.walk(local_output_dir):
        for f in files:
            fp = os.path.join(root, f)
            if os.path.isfile(fp):
                n_files += 1
                total += os.path.getsize(fp)
    mb = total / (1024 * 1024)
    scope = f"{len(include)} named file(s)" if include else "WHOLE DIRECTORY"
    warn = ""
    if not include:
        warn = ("\n⚠  no `include` given, so everything came down. Name the files "
                "you need -- see .claude/rules/tacc-fetch-rule.md")
    return (f"✅ {cfg['ssh_alias']}:{remote} → {local_output_dir}\n"
            f"   {scope}; {n_files} file(s), {mb:.1f} MB now in the destination{warn}")


if __name__ == "__main__":
    mcp.run()
