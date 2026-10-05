import yaml, subprocess, json, re, time, os, sys, statistics

# helper functions

def fill(to_be_replaced, values):
    for k, v in values.items():
        to_be_replaced = to_be_replaced.replace("<" + k + ">", str(v))
    return to_be_replaced

def campaign_values(cfg):
    return {
        "ms":        cfg["run"]["gcov_after_ms"],
        "rootfs":    os.path.join(cfg["run"]["app_dir"], cfg["run"]["rootfs"]),
        "port":      cfg["run"].get("port"),
        "host_port": cfg["run"].get("host_port")
    }

def run_values(cfg, base, run):
    v = dict(base)
    if run["kind"] == "injected":
        v["site"]   = run["site"]
        v["fault"]  = cfg["faults"][run["fault"]]["fi_fault"]
        v["nop"]    = run["nop"]
        v["period"] = run["period"]
    return v


#primary operations

def load_campaign(path):
    cfg=-1
    with open(path) as f:
        cfg = yaml.safe_load(f)
        oracles=cfg["oracles"]
        signals=set(cfg["signals"])
        for o in oracles:
            for a in o.get("all_of") or []:
                if(a not in signals):
                    raise RuntimeError(f"Signal {a} in oracle {o} invalid")
            for a in o.get("none_of") or []:
                if(a not in signals):
                    raise RuntimeError(f"Signal {a} in oracle {o} invalid")
            for a in o.get("any_of") or []:
                if(a not in signals):
                    raise RuntimeError(f"Signal {a} in oracle {o} invalid")

        faults = cfg["faults"]
        names = {o["name"] for o in oracles}

        for fault, spec in faults.items():
            for adm in spec["admissible"]:
                if(adm not in names):
                    raise RuntimeError(f"Fault {adm} marked admissible doesn't exist")
    
        duration = cfg["workload"]["client"]["duration_s"]
        if(not isinstance(duration, (int, float))):
            raise RuntimeError(f"Duration is not a number")
    return cfg

def verify_image(cfg):
    app = cfg["run"]["app_dir"]
    env = dict(os.environ, PWD=app)
    p = subprocess.run(["make", f"-j{cfg["build"]["jobs"]}"], cwd=app, env=env, capture_output=True, text=True)
    if(p.returncode != 0):
        raise RuntimeError(p.stderr)
    path_dbg = os.path.join(cfg["run"]["app_dir"], cfg["run"]["kernel"] + ".dbg")
    d=subprocess.run(["readelf", "-SW", path_dbg], capture_output=True, text=True)
    if(d.returncode != 0):
        raise RuntimeError(d.stderr)
        
    for line in d.stdout.splitlines():
        if ".uk_fitab" in line:
            break
    else:
        raise RuntimeError(f"Section .uk_fitab is absent: image without hooks")

    
    parts = line.split()
    i = parts.index(".uk_fitab")
    size = int(parts[i + 4], 16) # i+1 PROGBITS, i+2 addr, i+3 offset, i+4 size
    if(size%64 ==0 and size // 64 >= len(cfg["matrix"]["sites"])):
        return
    else:
        raise RuntimeError(f"Size of the ukfi table is not right")

def enumerate_runs(cfg):
    runs=[]

    count = cfg["protocol"]["baseline"]["count"]
    for i in range(count):
        runs.append({"site": None, "fault": None, "nop": None, "kind": "baseline", "id": f"baseline-{i}"})

    matrix=cfg["matrix"]
    n=0
    b=0
    every=cfg["protocol"]["baseline"]["interleave_every"]
    for site, spec in matrix["sites"].items():
        for fault in matrix["faults"]:
            if(spec["can_fail"] or fault != "error"):
                nops = spec["fi_nop"]
                for nop in nops:
                    runs.append({"site": site, "fault": fault, "nop": nop, "kind": "injected", "period": cfg["faults"][fault].get("fi_period_override", matrix["fi_period"]), "id": f"{site}-{fault}-{nop}"})
                    n+=1
                    if(n%every ==0):
                        runs.append({"site": None, "fault": None, "nop": None, "kind": "baseline", "id": f"baseline-{count+b}"})
                        b+=1

    complete = []
    for rnd in range(1, cfg["protocol"]["rounds"]+1):
        for r in runs:
            riga = dict(r)
            riga["round"] = rnd
            complete.append(riga)
    return complete

# execution of a run

def reset_state(cfg, v) -> None:
    for string in cfg["run"]["reset"]:
        res = fill(string, v) #swaps only rootfs
        if "<" in res:
            raise RuntimeError(f"[reset_state] Value not found in: {res}")
        subprocess.run(res, shell=True, cwd=cfg["run"]["app_dir"])

def build_append(cfg, run, v):
    t = cfg["run"]["append"]["baseline" if run["kind"] == "baseline" else "injected"]
    res = fill(t, v) #swaps only site, fault, nop, period, ms
    if "<" in res:
        raise RuntimeError(f"[build_append] Value not found in: {res}")
    return res

def launch_guest(cfg, append, logpath):
    r = cfg["run"]
    app = r["app_dir"]
    rootfs = os.path.join(app, r["rootfs"])

    argv = [
        r["qemu"],
        "-kernel", os.path.join(app, r["kernel"]),
        "-nographic",
        "-m", r["memory"],
        "-accel", r["accel"],
        "-cpu", "host",
        "-netdev", f"user,id=n0,hostfwd={r['hostfwd']}",
        "-device", "virtio-net-pci,netdev=n0",
        "-fsdev", f"local,id=myid,path={rootfs},security_model=none",
        "-device", f"virtio-9p-pci,fsdev=myid,mount_tag={r['mount_tag']},disable-modern=on,disable-legacy=off",
    ]
    for d in r["devices"]:
        argv += d.split()
    argv += ["-append", append]

    f = open(logpath, "w")
    proc = subprocess.Popen(argv, cwd=app, stdout=f, stderr=subprocess.STDOUT)
    t = time.time()
    return proc, f, t

def wait_ready(cfg, proc, v):
    r= cfg["workload"]["readiness"]
    cmd = fill(r["command"],v)
    if "<" in cmd:
        raise RuntimeError(f"[wait_ready] Value not found in: {cmd}")
    expect = r["expect"]
    interval_ms=r["interval_ms"]
    deadline_s=r["deadline_s"]
    t_0 = time.time()
    t_f = t_0 + deadline_s
    while (time.time()<=t_f):
        p = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        if expect in (p.stdout + p.stderr):
            return (time.time()-t_0)*1000
        if proc.poll() is not None:
            return None #dead guest
        time.sleep(interval_ms/1000)
    return None

def run_client(cfg, v):
    command = fill(cfg["workload"]["client"]["command"], v)
    if "<" in command:
        raise RuntimeError(f"[run_client] Value not found in: {command}")
    try:
        t1=time.time()
        p=subprocess.run(command, shell=True, capture_output=True, text=True, timeout=cfg["timeout"])
        t2=time.time()
        d={"exit": p.returncode, "stdout": p.stdout + p.stderr, "duration_s": t2-t1}
    except subprocess.TimeoutExpired:
        d={"exit": None, "stdout": "", "duration_s": cfg["timeout"]}

    return d

def collect_guest(proc, logpath, timeout):   # {'exit_code','timed_out','log'}
    timed_out=False
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        timed_out=True

    text=""
    with open(logpath, errors="replace") as f:
        text=f.read()

    return {"exit_code": proc.returncode, "timed_out": timed_out, "log": text}


# interpretation of results

def window(log, until) -> str:
    pref = log.find(until)
    if(pref==-1):
        return log
    else:
        return log[:pref]

def parse_metrics(cfg, stdout) -> dict:
    d = {}
    if(cfg["workload"]["metrics_parser"] == "redis_benchmark"):
        throughput = re.search(r"throughput summary:\s+([\d.]+)", stdout)
        if(throughput == None):
            throughput = None
        else:
            throughput = float(throughput.group(1))
        # il client troncato (crash, hang) non arriva a stampare le statistiche:
        # servono None, non un valore inventato, perche' "assente" e' un dato
        lines = stdout.splitlines()
        i=0
        for line in lines:
            if "latency summary (msec):" in line:
                break
            else:
                i+=1
        if(i+2 < len(lines)):
            latencies = lines[i+2].split()
        else:
            latencies=[]
        if(len(latencies) >= 6):
            avg = float(latencies[0])
            p99 = float(latencies[4])
            mx  = float(latencies[5])
        else:
            avg = p99 = mx = None
        d = {"app" : cfg["name"], "throughput_rps":throughput, "average_latency": avg, "latency_p99": p99, "latency_max_ms": mx}

    elif(cfg["workload"]["metrics_parser"] == "apache_bench"):
        req_per_sec = re.search(r"Requests per second:\s+([\d.]+)", stdout)
        failed_req = re.search(r"Failed requests:\s+(\d+)", stdout)
        longest_req = re.search(r"^\s*100%\s+(\d+)" , stdout, re.MULTILINE)
        non_200_OK = re.search(r"Non-2xx responses:\s+(\d+)", stdout)
        if(req_per_sec == None):
            req_per_sec = None
        else:
            req_per_sec = float(req_per_sec.group(1))
        if(failed_req == None):
            failed_req =0
        else:
            failed_req = int(failed_req.group(1))
        if(longest_req == None):
            longest_req = None
        else:
            longest_req = float(longest_req.group(1))
        if(non_200_OK == None):
            non_200_OK =0
        else:
            non_200_OK = float(non_200_OK.group(1))
        d= {"app": cfg["name"], "throughput_rps": req_per_sec, "failed_requests": failed_req, "longest_request": longest_req, "non_2xx": non_200_OK}
    else:
        raise RuntimeError("Workload not yet supported")
    
    return d

def evaluate_signals(cfg, guest, client, metrics, run, baseline):
    log = guest["log"]
    marker = cfg["signals"]["clear_shutdown"]["pattern"]
    win = window(log, marker)
    factor = cfg["workload"]["degraded_if"]["duration_factor"]
    
    out = {}
    for name, spec in cfg["signals"].items():
        src  = spec.get("source")
        kind = spec.get("kind")

        # clear_shutdown needs to be searched in the entire log, the others don't
        text = log if name == "clear_shutdown" else win
        boolean = False 
        if(src == "guest_log"):
            if(kind== "log_order"):
                i = text.find(spec["pattern"])
                j = text.find(spec["before"])
                boolean = i != -1 and (j == -1 or i < j)
            else:
                boolean = spec["pattern"] in text
        elif(src=="runner" and kind == "timeout"):
            boolean = guest["timed_out"]
        elif(src=="client"):
            if(kind=="nonzero_exit"):
                boolean = client["exit"] != 0
            elif(kind =="nonzero_exit_or_bad_responses"):
                boolean = client["exit"] != 0 or metrics.get("non_2xx", 0) > 0 or metrics.get("failed_requests", 0) > 0
            elif(kind=="readiness_failed"):
                boolean = client["ready_ms"] is None
            elif(kind=="duration_factor"):
                # il client che non e' mai partito, o troncato, non e' "degradato":
                # quel caso lo coprono client_error e guest_never_ready
                boolean= (baseline is not None
                          and client["duration_s"] is not None
                          and client["duration_s"] > factor * baseline)
        elif(src=="config"):
            boolean= run["kind"] =="injected"
        else: 
            raise RuntimeError(f"kind sconosciuto: {src}/{kind}")

        out[name] = boolean
    return out


def classify(cfg, signals) -> dict:
    oracles = cfg["oracles"]
    check = True
    for o in oracles:
        ok = all(signals.get(s, False) for s in o.get("all_of") or [])
        if ok:
            ok = not any(signals.get(s, False) for s in o.get("none_of") or [])
        anyof = o.get("any_of") or []
        if ok and anyof:
            ok = any(signals.get(s, False) for s in anyof)
        if ok:
            return {"name": o["name"], "outcome": o["outcome"]}



# campaign

def write_row(path, row):
    with open(path, 'a') as f:
        f.write(json.dumps(row)+'\n')
        f.flush()
    return

def main():
    must_fire_violated=0
    infrastructure_errors=0
    resume_index=0

    # sys.argv[1] needs to be redis.yaml or nginx.yaml
    campaign_file = sys.argv[1]
    cfg = load_campaign("/srv/unikraft/unikraft/lib/ukfi/harness/campaigns/"+campaign_file)
    
    logdir=os.path.join(cfg["run"]["app_dir"], "logs")
    os.makedirs(logdir, exist_ok=True)

    verify_image(cfg)
    runs = enumerate_runs(cfg)

    baseline=None
    durations=[]
    base = campaign_values(cfg)
    results = fill(cfg["protocol"]["results"], base)

    if not os.path.isabs(results):
        results = os.path.join(os.path.dirname(os.path.abspath(__file__)), results)
    os.makedirs(os.path.dirname(results), exist_ok=True)


    if(os.path.exists(results)):
        with open(results) as res:
            for line in res:
                try:
                    json.loads(line)
                except ValueError:
                    break
                resume_index+=1

    for i, run in enumerate(runs):

        if i < resume_index:
            continue

        v=run_values(cfg, base, run)
        logpath = os.path.join(logdir, f"{run['id']}-r{run['round']}.log")

        reset_state(cfg, v)
        append = build_append(cfg, run, v)
        proc, logfile, t_launch = launch_guest(cfg, append, logpath)

        ready_ms= wait_ready(cfg, proc, v)

        if ready_ms is None:
            client = {"exit": None, "stdout": "", "duration_s": None}
        else:
            client = run_client(cfg, v)
        client["ready_ms"] = ready_ms


        remaining_time = max(0, cfg["timeout"] - (time.time()-t_launch))
        guest = collect_guest(proc, logpath, remaining_time)

        logfile.close()

        metrics = parse_metrics(cfg, client["stdout"])
        signals= evaluate_signals(cfg, guest, client, metrics, run, baseline)
        verdict = classify(cfg, signals)

        row = {**run, **signals, **metrics, "outcome": verdict["outcome"], 
                "oracle": verdict["name"], "ready_ms": ready_ms, 
                "duration_s": client["duration_s"], "qemu_exit": guest["exit_code"],
                "timed_out": guest["timed_out"], "timestamp": time.strftime("%Y%m%d-%H%M%S")}
        write_row(results, row)

        if run["kind"]=="baseline" and client["duration_s"] is not None:
            durations.append(client["duration_s"])
            baseline = statistics.median(durations)
        
        if run["kind"] == "injected" and cfg["faults"][run["fault"]]["must_fire"] and not signals["fault_fired"]:
            must_fire_violated += 1
        else:
            must_fire_violated = 0

        if must_fire_violated >= cfg["protocol"]["abort_if"]["consecutive_must_fire_failures"]:
            print("too many must_fire violated, ending the campaign")
            break


if __name__ == "__main__":
    main()
