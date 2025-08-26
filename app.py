from flask import Flask, render_template, request, redirect, url_for, send_file, make_response, send_from_directory
import json, os, datetime, re, io
import werkzeug

app = Flask(__name__)

# ===================== CONFIG / PERCORSI =====================
# Usa un disco persistente su Render impostando: DATA_ROOT=/var/data
DATA_ROOT = os.environ.get("DATA_ROOT", ".")
USERS_DIR = os.path.join(DATA_ROOT, "users")
os.makedirs(USERS_DIR, exist_ok=True)

ALLOWED_IMG = {"png", "jpg", "jpeg", "webp"}
TRAINING_DAYS = {"Monday", "Tuesday", "Thursday", "Friday"}  # Lunedì, Martedì, Giovedì, Venerdì


# ===================== MULTI-UTENTE UTILS =====================
def sanitize_user_id(uid: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_\-\.]", "_", (uid or "").strip()) or "default"

def get_current_user():
    uid = request.args.get("u") or request.cookies.get("u") or "default"
    return sanitize_user_id(uid)

def user_dirs(user_id):
    base = os.path.join(USERS_DIR, user_id)
    data_path = os.path.join(base, "data.json")
    up_dir = os.path.join(base, "uploads")
    os.makedirs(base, exist_ok=True)
    os.makedirs(up_dir, exist_ok=True)
    return data_path, up_dir

def load_data(user_id=None):
    uid = user_id or get_current_user()
    data_path, _ = user_dirs(uid)
    if not os.path.exists(data_path):
        data = {
            "giornaliero": [],
            "allenamenti": [],
            "alimentazione": [],
            "meal_plan": {
                "Monday":"training","Tuesday":"training","Wednesday":"rest",
                "Thursday":"training","Friday":"training","Saturday":"rest","Sunday":"rest"
            },
            "goals": {
                "kcal_training":1700,"kcal_rest":1500,
                "weight_start":61.0,"weight_target":55.0,"peso_attuale":None
            }
        }
        save_data(data, uid)
        return data
    with open(data_path, "r", encoding="utf-8") as f:
        return json.load(f)

def save_data(data, user_id=None):
    uid = user_id or get_current_user()
    data_path, _ = user_dirs(uid)
    with open(data_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def uploads_url(user_id):
    return f"/user_uploads/{user_id}"

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_IMG


# ===================== AFTER REQUEST: cookie utente =====================
@app.after_request
def set_user_cookie(resp):
    uid = request.args.get("u")
    if uid:
        resp.set_cookie("u", sanitize_user_id(uid), max_age=60*60*24*365)
    return resp


# ===================== DATE & HELPER =====================
def parse_date(date_str):
    try:
        return datetime.date.fromisoformat(date_str)
    except Exception:
        return datetime.date.today()

def get_date_from_request():
    qs = request.args.get("date")
    return parse_date(qs) if qs else datetime.date.today()

def weekday_en(d=None):
    if d is None:
        d = datetime.date.today()
    return d.strftime("%A")  # Monday..Sunday

def sum_float(x):
    try:
        return float(x)
    except:
        return 0.0


# ===================== PIANI BASE =====================
DEFAULT_MEAL_PLAN = {
    "training": {
        "kcal_target": 1700,
        "meals": [
            {"key":"colazione","label":"Yogurt greco + avena + frutta","planned_qty":350,"unit":"g","base":100,"kcal_base":110,"prot_base":7,"carb_base":15,"fat_base":2},
            {"key":"spuntino1","label":"Banana / frutta","planned_qty":1,"unit":"pz","base":1,"kcal_base":90,"prot_base":1,"carb_base":23,"fat_base":0.3},
            {"key":"pranzo","label":"Riso + Pollo + Verdure","planned_qty":350,"unit":"g","base":100,"kcal_base":160,"prot_base":14,"carb_base":20,"fat_base":3},
            {"key":"spuntino2","label":"Shake proteico (1 misurino ~25g)","planned_qty":1,"unit":"pz","base":1,"kcal_base":100,"prot_base":20,"carb_base":3,"fat_base":1},
            {"key":"cena","label":"Pesce + Patate + Verdure","planned_qty":350,"unit":"g","base":100,"kcal_base":140,"prot_base":15,"carb_base":12,"fat_base":3}
        ]
    },
    "rest": {
        "kcal_target": 1500,
        "meals": [
            {"key":"colazione","label":"Yogurt greco + frutta secca","planned_qty":300,"unit":"g","base":100,"kcal_base":140,"prot_base":9,"carb_base":10,"fat_base":6},
            {"key":"spuntino1","label":"Frutta","planned_qty":1,"unit":"pz","base":1,"kcal_base":70,"prot_base":0.5,"carb_base":18,"fat_base":0.2},
            {"key":"pranzo","label":"Riso + Tonno + Verdure","planned_qty":350,"unit":"g","base":100,"kcal_base":150,"prot_base":13,"carb_base":18,"fat_base":3},
            {"key":"spuntino2","label":"Fiocchi latte / bresaola","planned_qty":150,"unit":"g","base":100,"kcal_base":90,"prot_base":12,"carb_base":3,"fat_base":2},
            {"key":"cena","label":"Uova + Verdure + Pane integrale","planned_qty":2,"unit":"pz","base":1,"kcal_base":80,"prot_base":7,"carb_base":0.5,"fat_base":5}
        ]
    }
}

WORKOUT_PLAN = {
    "Monday":[
        {"esercizio":"Chest Press Machine","serie":"4","ripetizioni":"10-12"},
        {"esercizio":"Incline Chest Press Machine","serie":"3","ripetizioni":"12"},
        {"esercizio":"Pec Deck (Butterfly)","serie":"3","ripetizioni":"15"},
        {"esercizio":"Tricipiti ai cavi (Pushdown)","serie":"3","ripetizioni":"12"},
        {"esercizio":"Dips assistite (machine)","serie":"3","ripetizioni":"max"},
        {"esercizio":"Cardio Tapis Roulant","serie":"1","ripetizioni":"20 min"}],
    "Tuesday":[
        {"esercizio":"Lat Machine presa larga","serie":"4","ripetizioni":"10"},
        {"esercizio":"Seated Row Machine","serie":"3","ripetizioni":"12"},
        {"esercizio":"Pullover Machine / Close Pulldown","serie":"3","ripetizioni":"12"},
        {"esercizio":"Biceps Curl Machine","serie":"3","ripetizioni":"12"},
        {"esercizio":"Preacher Curl Machine","serie":"3","ripetizioni":"12"},
        {"esercizio":"Crunch Machine / Plank","serie":"3","ripetizioni":"20 reps / 1 min"}],
    "Thursday":[
        {"esercizio":"Leg Press 45°","serie":"4","ripetizioni":"12-15"},
        {"esercizio":"Hack Squat Machine","serie":"3","ripetizioni":"12"},
        {"esercizio":"Leg Extension","serie":"3","ripetizioni":"15"},
        {"esercizio":"Seated Leg Curl","serie":"3","ripetizioni":"12-15"},
        {"esercizio":"Abductor/Adductor Machine","serie":"3","ripetizioni":"15/15"},
        {"esercizio":"Calf Press (su Leg Press)","serie":"4","ripetizioni":"15"}],
    "Friday":[
        {"esercizio":"Shoulder Press Machine","serie":"4","ripetizioni":"10-12"},
        {"esercizio":"Lateral Raise Machine","serie":"3","ripetizioni":"15"},
        {"esercizio":"Rear Delt Fly Machine","serie":"3","ripetizioni":"12-15"},
        {"esercizio":"Shrug Machine / Smith","serie":"3","ripetizioni":"12"},
        {"esercizio":"Rotary Torso / Woodchopper","serie":"3","ripetizioni":"12-15"},
        {"esercizio":"Cardio Tapis Roulant","serie":"1","ripetizioni":"20 min"}]
}

EXERCISE_LIBRARY = {
    "Giorno1 — Petto/Spalle/Bicipiti":[
        {"esercizio":"Panca piana bilanciere"},
        {"esercizio":"Spinte su panca 30° manubri"},
        {"esercizio":"Croci ai cavi (stripping)"},
        {"esercizio":"Shoulder Press (test 12RM)"},
        {"esercizio":"Standing Lateral Raises"},
        {"esercizio":"Panca Scott bilanciere sagomato"},
        {"esercizio":"Curl martello manubri seduto"}],
    "Giorno2 — Dorso/Tricipiti":[
        {"esercizio":"Lat machine presa prona (test 12RM)"},
        {"esercizio":"Isolateral Pulldown (test 12RM)"},
        {"esercizio":"Pulley triangolo (1s fermo al petto)"},
        {"esercizio":"French press al cavo su panca 30°"},
        {"esercizio":"Push down corda"}],
    "Gambe/Petto/Dorso":[
        {"esercizio":"Leg Press (test 12RM)"},
        {"esercizio":"Leg Curl seduto"},
        {"esercizio":"Leg Extension (20-15-12)"},
        {"esercizio":"Spinte su panca piana manubri (test 10RM+)"},
        {"esercizio":"Low Row Machine"},
        {"esercizio":"Lat machine presa supina (3x12-10-8)"}]
}


# ===================== AGGREGATI & STATS =====================
def integratori_aggregate(data, ref_date, scope="daily"):
    items = data.get("giornaliero", [])
    ref = parse_date(ref_date) if isinstance(ref_date, str) else ref_date

    def in_scope(dt: datetime.date):
        if scope == "daily":
            return dt == ref
        if scope == "weekly":
            return dt.isocalendar()[:2] == ref.isocalendar()[:2]
        if scope == "monthly":
            return dt.year == ref.year and dt.month == ref.month
        return dt == ref

    tot = {"creatina_g":0.0,"preworkout_pill":0.0,"termogenico_pill":0.0,"proteine_g":0.0}
    for r in items:
        try:
            dt = datetime.date.fromisoformat(r.get("data","1900-01-01"))
        except Exception:
            continue
        if not in_scope(dt):
            continue
        tot["creatina_g"]      += sum_float(r.get("q_creatina_g",0))
        tot["preworkout_pill"] += sum_float(r.get("q_preworkout_pill",0))
        tot["termogenico_pill"]+= sum_float(r.get("q_termogenico_pill",0))
        tot["proteine_g"]      += sum_float(r.get("q_proteine_g",0))
    for k in tot: tot[k] = round(tot[k],2)
    return tot

def _first_int(s):
    if not s: return 0
    m = re.search(r"\d+", str(s))
    return int(m.group()) if m else 0

def _float_or_zero(x):
    try: return float(x)
    except: return 0.0

def parse_set_details(s):
    if not s: return 0, 0.0
    total_reps, volume = 0, 0.0
    for token in str(s).split(","):
        token = token.strip().replace("@ ", "@")
        if "@" in token:
            reps_str, load_str = token.split("@", 1)
            try:
                reps = float(reps_str.strip())
                load = float(load_str.strip())
                total_reps += int(reps)
                volume += reps * load
            except:
                continue
    return total_reps, round(volume,2)

def compute_training_stats(sessions):
    stats = {}
    for s in sessions:
        d = s.get("data")
        if not d: continue
        ex_list = s.get("ex") or []
        done = 0; vol = 0.0
        for e in ex_list:
            if e.get("fatto"): done += 1
            setdet = e.get("set_dettagli")
            if setdet:
                _, v = parse_set_details(setdet)
                vol += v
            else:
                serie = _first_int(e.get("serie"))
                reps  = _first_int(e.get("ripetizioni"))
                load  = _float_or_zero(e.get("carico"))
                if serie and reps and load:
                    vol += serie * reps * load
        cur = stats.get(d, {"ex_done":0,"volume":0.0})
        cur["ex_done"] += done
        cur["volume"] += vol
        stats[d] = cur
    out = []
    for d in sorted(stats.keys()):
        out.append({"data":d,"ex_done":stats[d]["ex_done"],"volume":round(stats[d]["volume"],1)})
    return out


# ===================== ROUTES: USER / EXPORT / IMPORT / UPLOADS =====================
@app.route("/switch_user", methods=["POST"])
def switch_user():
    uid = sanitize_user_id(request.form.get("user_id") or "default")
    resp = make_response(redirect(url_for("diario", u=uid)))
    resp.set_cookie("u", uid, max_age=60*60*24*365)
    return resp

@app.route("/export", methods=["GET"])
def export_user_data():
    uid = get_current_user()
    data = load_data(uid)
    buf = io.BytesIO(json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"))
    fname = f"{uid}_fitness_export.json"
    return send_file(buf, mimetype="application/json", as_attachment=True, download_name=fname)

@app.route("/import", methods=["POST"])
def import_user_data():
    uid = get_current_user()
    up = request.files.get("file")
    if not up:
        return redirect(url_for("diario", u=uid))
    try:
        payload = json.load(up.stream)
    except Exception:
        return redirect(url_for("diario", u=uid))
    cur = load_data(uid)
    for key, val in payload.items():
        if key in {"giornaliero","allenamenti","alimentazione"} and isinstance(val, list):
            cur.setdefault(key, []); cur[key].extend(val)
        elif key in {"meal_plan","goals"} and isinstance(val, dict):
            cur.setdefault(key, {}); cur[key].update(val)
        else:
            cur[key] = val
    save_data(cur, uid)
    return redirect(url_for("diario", u=uid))

@app.route("/user_uploads/<user_id>/<path:filename>")
def user_uploads(user_id, filename):
    _, up_dir = user_dirs(sanitize_user_id(user_id))
    return send_from_directory(up_dir, filename)


# ===================== ROUTES PRINCIPALI =====================
@app.route("/")
def index():
    return redirect(url_for("diario"))

# --------- DIARIO (solo lettura integratori; foto/misure; gauge peso) ---------
@app.route("/diario", methods=["GET"])
def diario():
    uid = get_current_user()
    data = load_data(uid)

    ref_date = get_date_from_request()
    scope = request.args.get("scope") or "daily"

    agg = integratori_aggregate(data, ref_date, scope)

    def in_scope(dt: datetime.date):
        if scope == "daily":
            return dt == ref_date
        if scope == "weekly":
            return dt.isocalendar()[:2] == ref_date.isocalendar()[:2]
        if scope == "monthly":
            return dt.year == ref_date.year and dt.month == ref_date.month
        return dt == ref_date

    last_days = []
    for i in range(0, 30):
        d = ref_date - datetime.timedelta(days=i)
        s = integratori_aggregate(data, d, "daily")
        s.update({"data": d.isoformat()})
        last_days.append(s)

    photos = []
    measures_latest = None
    for s in data.get("allenamenti", []):
        dstr = s.get("data")
        if not dstr: continue
        try:
            d = datetime.date.fromisoformat(dstr)
        except Exception:
            continue
        if not in_scope(d): continue
        if s.get("foto"):
            photos.append({"data": dstr, "url": s["foto"]})
        mis = s.get("misure") or {}
        if any(mis.values()):
            if (measures_latest is None) or (dstr >= measures_latest.get("data","")):
                measures_latest = {"data": dstr, **mis}

    goals = data.get("goals", {})
    start_weight = goals.get("weight_start", 61.0)
    target_weight = goals.get("weight_target", 55.0)
    cur_weight = goals.get("peso_attuale", None)
    if cur_weight is None:
        for r in sorted(data.get("giornaliero", []), key=lambda x: x.get("data","")):
            try:
                d = datetime.date.fromisoformat(r.get("data","1900-01-01"))
            except Exception:
                continue
            if d <= ref_date and r.get("peso"):
                try: cur_weight = float(r.get("peso"))
                except: pass
    if cur_weight is None:
        for r in sorted(data.get("giornaliero", []), key=lambda x: x.get("data",""), reverse=True):
            if r.get("peso"):
                try:
                    cur_weight = float(r.get("peso")); break
                except: continue

    try:
        span = max((start_weight - target_weight), 0.0001)
        prog = (start_weight - (cur_weight if cur_weight is not None else start_weight))
        progress_pct = max(0, min(100, round(100 * (prog / span), 1)))
    except Exception:
        progress_pct = 0

    weight_block = {
        "start": round(start_weight, 1),
        "current": round(cur_weight, 1) if cur_weight is not None else None,
        "target": round(target_weight, 1),
        "progress_pct": progress_pct
    }

    alim_records = sorted(data.get("alimentazione", []), key=lambda r: r.get("data",""), reverse=True)

    return render_template(
        "diario.html",
        uid=uid,
        ref_date=ref_date.isoformat(),
        scope=scope,
        agg=agg,
        last_days=last_days,
        photos=sorted(photos, key=lambda x: x["data"], reverse=True),
        measures_latest=measures_latest,
        weight_block=weight_block,
        alim_records=alim_records
    )

# --------- ALLENAMENTI (GET/POST) ---------
@app.route("/allenamenti", methods=["GET","POST"])
def allenamenti():
    uid = get_current_user()
    data = load_data(uid)
    chosen_date = get_date_from_request()
    wd = weekday_en(chosen_date)
    plan_today = WORKOUT_PLAN.get(wd, [])
    _, UPLOAD_DIR = user_dirs(uid)

    if request.method == "POST":
        prewo = bool(request.form.get("preworkout"))
        protpo = bool(request.form.get("proteine_post"))
        creapo = bool(request.form.get("creatina_post"))
        q_pre = request.form.get("q_preworkout_pill") or ""
        q_prot = request.form.get("q_proteine_post_g") or ""
        q_crea = request.form.get("q_creatina_post_g") or ""

        petto = request.form.get("mis_petto") or ""
        vita  = request.form.get("mis_vita") or ""
        fianchi = request.form.get("mis_fianchi") or ""
        coscia = request.form.get("mis_coscia") or ""
        braccio = request.form.get("mis_braccio") or ""
        foto_url = ""
        file = request.files.get("foto")
        if file and file.filename and allowed_file(file.filename):
            fname = werkzeug.utils.secure_filename(f"{chosen_date.isoformat()}_{file.filename}")
            file.save(os.path.join(UPLOAD_DIR, fname))
            foto_url = f"{uploads_url(uid)}/{fname}"

        session = {
            "data": chosen_date.isoformat(),
            "giorno": request.form.get("giorno") or wd,
            "ex": [],
            "preworkout": prewo,
            "proteine_post": protpo,
            "creatina_post": creapo,
            "q_preworkout_pill": q_pre,
            "q_proteine_post_g": q_prot,
            "q_creatina_post_g": q_crea,
            "misure": {"petto":petto,"vita":vita,"fianchi":fianchi,"coscia":coscia,"braccio":braccio},
            "foto": foto_url,
            "completion": 0
        }

        selected_count = 0; done_count = 0

        # Piano del giorno
        for idx, ex in enumerate(plan_today):
            if request.form.get(f"plan_{idx}_use"):
                done = bool(request.form.get(f"plan_{idx}_done"))
                serie = request.form.get(f"plan_{idx}_serie") or ex["serie"]
                reps  = request.form.get(f"plan_{idx}_ripetizioni") or ex["ripetizioni"]
                load  = request.form.get(f"plan_{idx}_carico") or ""
                setdet= request.form.get(f"plan_{idx}_setdet") or ""
                diff  = request.form.get(f"plan_{idx}_diff") or ""
                session["ex"].append({
                    "esercizio": ex["esercizio"],
                    "serie": serie, "ripetizioni": reps, "carico": load,
                    "set_dettagli": setdet, "difficolta": diff,
                    "fatto": done
                })
                selected_count += 1
                if done: done_count += 1

        # Libreria
        lib_items = list(EXERCISE_LIBRARY.items())
        for cat_idx, (cat_name, items) in enumerate(lib_items):
            for i, item in enumerate(items):
                if request.form.get(f"lib_{cat_idx}_{i}_use"):
                    done = bool(request.form.get(f"lib_{cat_idx}_{i}_done"))
                    serie = request.form.get(f"lib_{cat_idx}_{i}_serie") or ""
                    reps  = request.form.get(f"lib_{cat_idx}_{i}_ripetizioni") or ""
                    load  = request.form.get(f"lib_{cat_idx}_{i}_carico") or ""
                    setdet= request.form.get(f"lib_{cat_idx}_{i}_setdet") or ""
                    diff  = request.form.get(f"lib_{cat_idx}_{i}_diff") or ""
                    session["ex"].append({
                        "esercizio": item["esercizio"],
                        "serie": serie, "ripetizioni": reps, "carico": load,
                        "set_dettagli": setdet, "difficolta": diff,
                        "fatto": done
                    })
                    selected_count += 1
                    if done: done_count += 1

        # Custom
        cust_idx = 0
        while True:
            name = request.form.get(f"cust_{cust_idx}_name")
            serie = request.form.get(f"cust_{cust_idx}_serie")
            reps  = request.form.get(f"cust_{cust_idx}_ripetizioni")
            load  = request.form.get(f"cust_{cust_idx}_carico")
            setdet= request.form.get(f"cust_{cust_idx}_setdet")
            diff  = request.form.get(f"cust_{cust_idx}_diff")
            done  = bool(request.form.get(f"cust_{cust_idx}_done"))
            if not any([name, serie, reps, load, setdet, diff, done]):
                break
            if name:
                session["ex"].append({
                    "esercizio": name, "serie": serie or "", "ripetizioni": reps or "", "carico": load or "",
                    "set_dettagli": setdet or "", "difficolta": (diff or ""), "fatto": done
                })
                selected_count += 1
                if done: done_count += 1
            cust_idx += 1

        session["completion"] = int(100 * (done_count / selected_count)) if selected_count else 0
        data["allenamenti"].append(session)

        # Sync diario (integratori per la stessa data)
        diary = None
        for r in data["giornaliero"]:
            if r.get("data") == chosen_date.isoformat():
                diary = r; break
        if diary is None:
            diary = {"data": chosen_date.isoformat(),
                     "creatina":False,"preworkout":False,"termogenico":False,"proteine":False,
                     "q_creatina_g":"","q_preworkout_pill":"","q_termogenico_pill":"","q_proteine_g":"",
                     "peso":"","vita":"","fianchi":"","note":""}
            data["giornaliero"].append(diary)
        if prewo:
            diary["preworkout"] = True
            diary["q_preworkout_pill"] = str(sum_float(diary.get("q_preworkout_pill")) + sum_float(q_pre))
        if protpo:
            diary["proteine"] = True
            diary["q_proteine_g"] = str(sum_float(diary.get("q_proteine_g")) + sum_float(q_prot))
        if creapo:
            diary["creatina"] = True
            diary["q_creatina_g"] = str(sum_float(diary.get("q_creatina_g")) + sum_float(q_crea))

        save_data(data, uid)
        return redirect(url_for("allenamenti", u=uid, date=chosen_date.isoformat()))

    records_day = [s for s in data.get("allenamenti", []) if s.get("data") == chosen_date.isoformat()]
    return render_template("allenamenti.html",
                           uid=uid, plan_today=plan_today, weekday=wd,
                           exercise_library=EXERCISE_LIBRARY,
                           records=records_day, chosen_date=chosen_date.isoformat())

# --------- ALIMENTAZIONE (GET/POST con target kcal del giorno) ---------
@app.route("/alimentazione", methods=["GET","POST"])
def alimentazione():
    uid = get_current_user()
    data = load_data(uid)
    chosen_date = get_date_from_request()
    wd = weekday_en(chosen_date)
    plan_type = data["meal_plan"].get(wd, "rest")

    goals = data.get("goals", {})
    base_kcal_target = goals.get("kcal_training") if plan_type=="training" else goals.get("kcal_rest")
    plan = DEFAULT_MEAL_PLAN["training" if plan_type=="training" else "rest"]

    existing = None
    for a in data.get("alimentazione", []):
        if a.get("data") == chosen_date.isoformat():
            existing = a; break

    if request.method == "POST":
        try:
            kcal_target_day = int(float(request.form.get("kcal_target") or base_kcal_target))
        except:
            kcal_target_day = int(base_kcal_target or plan["kcal_target"])

        kcal_tot = prot_tot = carb_tot = fat_tot = 0.0
        m = {
            "data": chosen_date.isoformat(),
            "plan_type": plan_type,
            "kcal_target": kcal_target_day,
            "meals": [],
            "kcal": 0, "proteine_g": 0, "carbo_g": 0, "grassi_g": 0,
            "creatina_mattino": bool(request.form.get("creatina_mattino")),
            "termogenico_mattino": bool(request.form.get("termogenico_mattino")),
            "proteine_pasto": bool(request.form.get("proteine_pasto")),
            "q_creatina_mattino_g": request.form.get("q_creatina_mattino_g") or "",
            "q_termogenico_mattino_pill": request.form.get("q_termogenico_mattino_pill") or "",
            "q_proteine_pasto_g": request.form.get("q_proteine_pasto_g") or "",
            "note": request.form.get("note") or "",
            "completion": 0
        }

        total_meals = len(plan["meals"]); consumed_count = 0

        for meal in plan["meals"]:
            key = meal["key"]
            consumed = bool(request.form.get(f"meal_{key}_done"))
            qty = request.form.get(f"meal_{key}_qty") or ""
            try: qty_num = float(qty)
            except: qty_num = 0.0

            base  = float(request.form.get(f"meal_{key}_base") or meal["base"])
            kcalB = float(request.form.get(f"meal_{key}_kcal_base") or 0)
            protB = float(request.form.get(f"meal_{key}_prot_base") or 0)
            carbB = float(request.form.get(f"meal_{key}_carb_base") or 0)
            fatB  = float(request.form.get(f"meal_{key}_fat_base") or 0)

            factor = (qty_num / base) if base else 0.0
            mk = round(factor * kcalB, 1)
            mp = round(factor * protB, 1)
            mc = round(factor * carbB, 1)
            mf = round(factor * fatB, 1)

            if consumed:
                consumed_count += 1
                kcal_tot += mk; prot_tot += mp; carb_tot += mc; fat_tot += mf

            m["meals"].append({
                "key": key, "label": meal["label"],
                "planned_qty": meal["planned_qty"], "unit": meal["unit"],
                "consumed": consumed, "consumed_qty": qty_num,
                "base": base, "kcal_base": kcalB, "prot_base": protB, "carb_base": carbB, "fat_base": fatB,
                "meal_kcal": mk, "meal_prot": mp, "meal_carb": mc, "meal_fat": mf
            })

        m["completion"] = int(100 * (consumed_count / total_meals)) if total_meals else 0
        m["kcal"] = round(kcal_tot, 0)
        m["proteine_g"] = round(prot_tot, 1)
        m["carbo_g"] = round(carb_tot, 1)
        m["grassi_g"] = round(fat_tot, 1)

        if existing:
            data["alimentazione"] = [x for x in data["alimentazione"] if x.get("data") != chosen_date.isoformat()]
        data["alimentazione"].append(m)

        # sync diario integratori (mattino/pasto)
        diary = None
        for r in data["giornaliero"]:
            if r.get("data") == chosen_date.isoformat():
                diary = r; break
        if diary is None:
            diary = {"data": chosen_date.isoformat(),
                     "creatina":False,"preworkout":False,"termogenico":False,"proteine":False,
                     "q_creatina_g":"","q_preworkout_pill":"","q_termogenico_pill":"","q_proteine_g":"",
                     "peso":"","vita":"","fianchi":"","note":""}
            data["giornaliero"].append(diary)

        if m["creatina_mattino"]:
            diary["creatina"] = True
            diary["q_creatina_g"] = str(sum_float(diary.get("q_creatina_g")) + sum_float(m["q_creatina_mattino_g"]))
        if m["proteine_pasto"]:
            diary["proteine"] = True
            diary["q_proteine_g"] = str(sum_float(diary.get("q_proteine_g")) + sum_float(m["q_proteine_pasto_g"]))
        if m["termogenico_mattino"]:
            diary["termogenico"] = True
            diary["q_termogenico_pill"] = str(sum_float(diary.get("q_termogenico_pill")) + sum_float(m["q_termogenico_mattino_pill"]))

        save_data(data, uid)
        return redirect(url_for("alimentazione", u=uid, date=chosen_date.isoformat()))

    records_day = [a for a in data.get("alimentazione", []) if a.get("data") == chosen_date.isoformat()]
    base_kcal_target = base_kcal_target or plan["kcal_target"]
    return render_template("alimentazione.html",
                           uid=uid, plan=plan, plan_type=plan_type,
                           plan_kcal_target=base_kcal_target,
                           records=records_day, chosen_date=chosen_date.isoformat())

# --------- PROGRESSI ---------
@app.route("/progressi")
def progressi():
    uid = get_current_user()
    data = load_data(uid)
    diario_records = data.get("giornaliero", [])
    try:
        diario_records = sorted(diario_records, key=lambda r: r["data"])
    except Exception:
        pass
    training_stats = compute_training_stats(data.get("allenamenti", []))
    return render_template("progressi.html", uid=uid, records=diario_records, training_stats=training_stats)

# --------- OBIETTIVI ---------
@app.route("/obiettivi", methods=["GET","POST"])from flask import Flask, render_template, request, redirect, url_for, send_file, make_response, send_from_directory
import json, os, datetime, re, io
import werkzeug

app = Flask(__name__)

# ===================== CONFIG / PERCORSI =====================
# Usa un disco persistente su Render impostando: DATA_ROOT=/var/data
DATA_ROOT = os.environ.get("DATA_ROOT", ".")
USERS_DIR = os.path.join(DATA_ROOT, "users")
os.makedirs(USERS_DIR, exist_ok=True)

ALLOWED_IMG = {"png", "jpg", "jpeg", "webp"}
TRAINING_DAYS = {"Monday", "Tuesday", "Thursday", "Friday"}  # Lunedì, Martedì, Giovedì, Venerdì


# ===================== MULTI-UTENTE UTILS =====================
def sanitize_user_id(uid: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_\-\.]", "_", (uid or "").strip()) or "default"

def get_current_user():
    uid = request.args.get("u") or request.cookies.get("u") or "default"
    return sanitize_user_id(uid)

def user_dirs(user_id):
    base = os.path.join(USERS_DIR, user_id)
    data_path = os.path.join(base, "data.json")
    up_dir = os.path.join(base, "uploads")
    os.makedirs(base, exist_ok=True)
    os.makedirs(up_dir, exist_ok=True)
    return data_path, up_dir

def load_data(user_id=None):
    uid = user_id or get_current_user()
    data_path, _ = user_dirs(uid)
    if not os.path.exists(data_path):
        data = {
            "giornaliero": [],
            "allenamenti": [],
            "alimentazione": [],
            "meal_plan": {
                "Monday":"training","Tuesday":"training","Wednesday":"rest",
                "Thursday":"training","Friday":"training","Saturday":"rest","Sunday":"rest"
            },
            "goals": {
                "kcal_training":1700,"kcal_rest":1500,
                "weight_start":61.0,"weight_target":55.0,"peso_attuale":None
            }
        }
        save_data(data, uid)
        return data
    with open(data_path, "r", encoding="utf-8") as f:
        return json.load(f)

def save_data(data, user_id=None):
    uid = user_id or get_current_user()
    data_path, _ = user_dirs(uid)
    with open(data_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def uploads_url(user_id):
    return f"/user_uploads/{user_id}"

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_IMG


# ===================== AFTER REQUEST: cookie utente =====================
@app.after_request
def set_user_cookie(resp):
    uid = request.args.get("u")
    if uid:
        resp.set_cookie("u", sanitize_user_id(uid), max_age=60*60*24*365)
    return resp


# ===================== DATE & HELPER =====================
def parse_date(date_str):
    try:
        return datetime.date.fromisoformat(date_str)
    except Exception:
        return datetime.date.today()

def get_date_from_request():
    qs = request.args.get("date")
    return parse_date(qs) if qs else datetime.date.today()

def weekday_en(d=None):
    if d is None:
        d = datetime.date.today()
    return d.strftime("%A")  # Monday..Sunday

def sum_float(x):
    try:
        return float(x)
    except:
        return 0.0


# ===================== PIANI BASE =====================
DEFAULT_MEAL_PLAN = {
    "training": {
        "kcal_target": 1700,
        "meals": [
            {"key":"colazione","label":"Yogurt greco + avena + frutta","planned_qty":350,"unit":"g","base":100,"kcal_base":110,"prot_base":7,"carb_base":15,"fat_base":2},
            {"key":"spuntino1","label":"Banana / frutta","planned_qty":1,"unit":"pz","base":1,"kcal_base":90,"prot_base":1,"carb_base":23,"fat_base":0.3},
            {"key":"pranzo","label":"Riso + Pollo + Verdure","planned_qty":350,"unit":"g","base":100,"kcal_base":160,"prot_base":14,"carb_base":20,"fat_base":3},
            {"key":"spuntino2","label":"Shake proteico (1 misurino ~25g)","planned_qty":1,"unit":"pz","base":1,"kcal_base":100,"prot_base":20,"carb_base":3,"fat_base":1},
            {"key":"cena","label":"Pesce + Patate + Verdure","planned_qty":350,"unit":"g","base":100,"kcal_base":140,"prot_base":15,"carb_base":12,"fat_base":3}
        ]
    },
    "rest": {
        "kcal_target": 1500,
        "meals": [
            {"key":"colazione","label":"Yogurt greco + frutta secca","planned_qty":300,"unit":"g","base":100,"kcal_base":140,"prot_base":9,"carb_base":10,"fat_base":6},
            {"key":"spuntino1","label":"Frutta","planned_qty":1,"unit":"pz","base":1,"kcal_base":70,"prot_base":0.5,"carb_base":18,"fat_base":0.2},
            {"key":"pranzo","label":"Riso + Tonno + Verdure","planned_qty":350,"unit":"g","base":100,"kcal_base":150,"prot_base":13,"carb_base":18,"fat_base":3},
            {"key":"spuntino2","label":"Fiocchi latte / bresaola","planned_qty":150,"unit":"g","base":100,"kcal_base":90,"prot_base":12,"carb_base":3,"fat_base":2},
            {"key":"cena","label":"Uova + Verdure + Pane integrale","planned_qty":2,"unit":"pz","base":1,"kcal_base":80,"prot_base":7,"carb_base":0.5,"fat_base":5}
        ]
    }
}

WORKOUT_PLAN = {
    "Monday":[
        {"esercizio":"Chest Press Machine","serie":"4","ripetizioni":"10-12"},
        {"esercizio":"Incline Chest Press Machine","serie":"3","ripetizioni":"12"},
        {"esercizio":"Pec Deck (Butterfly)","serie":"3","ripetizioni":"15"},
        {"esercizio":"Tricipiti ai cavi (Pushdown)","serie":"3","ripetizioni":"12"},
        {"esercizio":"Dips assistite (machine)","serie":"3","ripetizioni":"max"},
        {"esercizio":"Cardio Tapis Roulant","serie":"1","ripetizioni":"20 min"}],
    "Tuesday":[
        {"esercizio":"Lat Machine presa larga","serie":"4","ripetizioni":"10"},
        {"esercizio":"Seated Row Machine","serie":"3","ripetizioni":"12"},
        {"esercizio":"Pullover Machine / Close Pulldown","serie":"3","ripetizioni":"12"},
        {"esercizio":"Biceps Curl Machine","serie":"3","ripetizioni":"12"},
        {"esercizio":"Preacher Curl Machine","serie":"3","ripetizioni":"12"},
        {"esercizio":"Crunch Machine / Plank","serie":"3","ripetizioni":"20 reps / 1 min"}],
    "Thursday":[
        {"esercizio":"Leg Press 45°","serie":"4","ripetizioni":"12-15"},
        {"esercizio":"Hack Squat Machine","serie":"3","ripetizioni":"12"},
        {"esercizio":"Leg Extension","serie":"3","ripetizioni":"15"},
        {"esercizio":"Seated Leg Curl","serie":"3","ripetizioni":"12-15"},
        {"esercizio":"Abductor/Adductor Machine","serie":"3","ripetizioni":"15/15"},
        {"esercizio":"Calf Press (su Leg Press)","serie":"4","ripetizioni":"15"}],
    "Friday":[
        {"esercizio":"Shoulder Press Machine","serie":"4","ripetizioni":"10-12"},
        {"esercizio":"Lateral Raise Machine","serie":"3","ripetizioni":"15"},
        {"esercizio":"Rear Delt Fly Machine","serie":"3","ripetizioni":"12-15"},
        {"esercizio":"Shrug Machine / Smith","serie":"3","ripetizioni":"12"},
        {"esercizio":"Rotary Torso / Woodchopper","serie":"3","ripetizioni":"12-15"},
        {"esercizio":"Cardio Tapis Roulant","serie":"1","ripetizioni":"20 min"}]
}

EXERCISE_LIBRARY = {
    "Giorno1 — Petto/Spalle/Bicipiti":[
        {"esercizio":"Panca piana bilanciere"},
        {"esercizio":"Spinte su panca 30° manubri"},
        {"esercizio":"Croci ai cavi (stripping)"},
        {"esercizio":"Shoulder Press (test 12RM)"},
        {"esercizio":"Standing Lateral Raises"},
        {"esercizio":"Panca Scott bilanciere sagomato"},
        {"esercizio":"Curl martello manubri seduto"}],
    "Giorno2 — Dorso/Tricipiti":[
        {"esercizio":"Lat machine presa prona (test 12RM)"},
        {"esercizio":"Isolateral Pulldown (test 12RM)"},
        {"esercizio":"Pulley triangolo (1s fermo al petto)"},
        {"esercizio":"French press al cavo su panca 30°"},
        {"esercizio":"Push down corda"}],
    "Gambe/Petto/Dorso":[
        {"esercizio":"Leg Press (test 12RM)"},
        {"esercizio":"Leg Curl seduto"},
        {"esercizio":"Leg Extension (20-15-12)"},
        {"esercizio":"Spinte su panca piana manubri (test 10RM+)"},
        {"esercizio":"Low Row Machine"},
        {"esercizio":"Lat machine presa supina (3x12-10-8)"}]
}


# ===================== AGGREGATI & STATS =====================
def integratori_aggregate(data, ref_date, scope="daily"):
    items = data.get("giornaliero", [])
    ref = parse_date(ref_date) if isinstance(ref_date, str) else ref_date

    def in_scope(dt: datetime.date):
        if scope == "daily":
            return dt == ref
        if scope == "weekly":
            return dt.isocalendar()[:2] == ref.isocalendar()[:2]
        if scope == "monthly":
            return dt.year == ref.year and dt.month == ref.month
        return dt == ref

    tot = {"creatina_g":0.0,"preworkout_pill":0.0,"termogenico_pill":0.0,"proteine_g":0.0}
    for r in items:
        try:
            dt = datetime.date.fromisoformat(r.get("data","1900-01-01"))
        except Exception:
            continue
        if not in_scope(dt):
            continue
        tot["creatina_g"]      += sum_float(r.get("q_creatina_g",0))
        tot["preworkout_pill"] += sum_float(r.get("q_preworkout_pill",0))
        tot["termogenico_pill"]+= sum_float(r.get("q_termogenico_pill",0))
        tot["proteine_g"]      += sum_float(r.get("q_proteine_g",0))
    for k in tot: tot[k] = round(tot[k],2)
    return tot

def _first_int(s):
    if not s: return 0
    m = re.search(r"\d+", str(s))
    return int(m.group()) if m else 0

def _float_or_zero(x):
    try: return float(x)
    except: return 0.0

def parse_set_details(s):
    if not s: return 0, 0.0
    total_reps, volume = 0, 0.0
    for token in str(s).split(","):
        token = token.strip().replace("@ ", "@")
        if "@" in token:
            reps_str, load_str = token.split("@", 1)
            try:
                reps = float(reps_str.strip())
                load = float(load_str.strip())
                total_reps += int(reps)
                volume += reps * load
            except:
                continue
    return total_reps, round(volume,2)

def compute_training_stats(sessions):
    stats = {}
    for s in sessions:
        d = s.get("data")
        if not d: continue
        ex_list = s.get("ex") or []
        done = 0; vol = 0.0
        for e in ex_list:
            if e.get("fatto"): done += 1
            setdet = e.get("set_dettagli")
            if setdet:
                _, v = parse_set_details(setdet)
                vol += v
            else:
                serie = _first_int(e.get("serie"))
                reps  = _first_int(e.get("ripetizioni"))
                load  = _float_or_zero(e.get("carico"))
                if serie and reps and load:
                    vol += serie * reps * load
        cur = stats.get(d, {"ex_done":0,"volume":0.0})
        cur["ex_done"] += done
        cur["volume"] += vol
        stats[d] = cur
    out = []
    for d in sorted(stats.keys()):
        out.append({"data":d,"ex_done":stats[d]["ex_done"],"volume":round(stats[d]["volume"],1)})
    return out


# ===================== ROUTES: USER / EXPORT / IMPORT / UPLOADS =====================
@app.route("/switch_user", methods=["POST"])
def switch_user():
    uid = sanitize_user_id(request.form.get("user_id") or "default")
    resp = make_response(redirect(url_for("diario", u=uid)))
    resp.set_cookie("u", uid, max_age=60*60*24*365)
    return resp

@app.route("/export", methods=["GET"])
def export_user_data():
    uid = get_current_user()
    data = load_data(uid)
    buf = io.BytesIO(json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"))
    fname = f"{uid}_fitness_export.json"
    return send_file(buf, mimetype="application/json", as_attachment=True, download_name=fname)

@app.route("/import", methods=["POST"])
def import_user_data():
    uid = get_current_user()
    up = request.files.get("file")
    if not up:
        return redirect(url_for("diario", u=uid))
    try:
        payload = json.load(up.stream)
    except Exception:
        return redirect(url_for("diario", u=uid))
    cur = load_data(uid)
    for key, val in payload.items():
        if key in {"giornaliero","allenamenti","alimentazione"} and isinstance(val, list):
            cur.setdefault(key, []); cur[key].extend(val)
        elif key in {"meal_plan","goals"} and isinstance(val, dict):
            cur.setdefault(key, {}); cur[key].update(val)
        else:
            cur[key] = val
    save_data(cur, uid)
    return redirect(url_for("diario", u=uid))

@app.route("/user_uploads/<user_id>/<path:filename>")
def user_uploads(user_id, filename):
    _, up_dir = user_dirs(sanitize_user_id(user_id))
    return send_from_directory(up_dir, filename)


# ===================== ROUTES PRINCIPALI =====================
@app.route("/")
def index():
    return redirect(url_for("diario"))

# --------- DIARIO (solo lettura integratori; foto/misure; gauge peso) ---------
@app.route("/diario", methods=["GET"])
def diario():
    uid = get_current_user()
    data = load_data(uid)

    ref_date = get_date_from_request()
    scope = request.args.get("scope") or "daily"

    agg = integratori_aggregate(data, ref_date, scope)

    def in_scope(dt: datetime.date):
        if scope == "daily":
            return dt == ref_date
        if scope == "weekly":
            return dt.isocalendar()[:2] == ref_date.isocalendar()[:2]
        if scope == "monthly":
            return dt.year == ref_date.year and dt.month == ref_date.month
        return dt == ref_date

    last_days = []
    for i in range(0, 30):
        d = ref_date - datetime.timedelta(days=i)
        s = integratori_aggregate(data, d, "daily")
        s.update({"data": d.isoformat()})
        last_days.append(s)

    photos = []
    measures_latest = None
    for s in data.get("allenamenti", []):
        dstr = s.get("data")
        if not dstr: continue
        try:
            d = datetime.date.fromisoformat(dstr)
        except Exception:
            continue
        if not in_scope(d): continue
        if s.get("foto"):
            photos.append({"data": dstr, "url": s["foto"]})
        mis = s.get("misure") or {}
        if any(mis.values()):
            if (measures_latest is None) or (dstr >= measures_latest.get("data","")):
                measures_latest = {"data": dstr, **mis}

    goals = data.get("goals", {})
    start_weight = goals.get("weight_start", 61.0)
    target_weight = goals.get("weight_target", 55.0)
    cur_weight = goals.get("peso_attuale", None)
    if cur_weight is None:
        for r in sorted(data.get("giornaliero", []), key=lambda x: x.get("data","")):
            try:
                d = datetime.date.fromisoformat(r.get("data","1900-01-01"))
            except Exception:
                continue
            if d <= ref_date and r.get("peso"):
                try: cur_weight = float(r.get("peso"))
                except: pass
    if cur_weight is None:
        for r in sorted(data.get("giornaliero", []), key=lambda x: x.get("data",""), reverse=True):
            if r.get("peso"):
                try:
                    cur_weight = float(r.get("peso")); break
                except: continue

    try:
        span = max((start_weight - target_weight), 0.0001)
        prog = (start_weight - (cur_weight if cur_weight is not None else start_weight))
        progress_pct = max(0, min(100, round(100 * (prog / span), 1)))
    except Exception:
        progress_pct = 0

    weight_block = {
        "start": round(start_weight, 1),
        "current": round(cur_weight, 1) if cur_weight is not None else None,
        "target": round(target_weight, 1),
        "progress_pct": progress_pct
    }

    alim_records = sorted(data.get("alimentazione", []), key=lambda r: r.get("data",""), reverse=True)

    return render_template(
        "diario.html",
        uid=uid,
        ref_date=ref_date.isoformat(),
        scope=scope,
        agg=agg,
        last_days=last_days,
        photos=sorted(photos, key=lambda x: x["data"], reverse=True),
        measures_latest=measures_latest,
        weight_block=weight_block,
        alim_records=alim_records
    )

# --------- ALLENAMENTI (GET/POST) ---------
@app.route("/allenamenti", methods=["GET","POST"])
def allenamenti():
    uid = get_current_user()
    data = load_data(uid)
    chosen_date = get_date_from_request()
    wd = weekday_en(chosen_date)
    plan_today = WORKOUT_PLAN.get(wd, [])
    _, UPLOAD_DIR = user_dirs(uid)

    if request.method == "POST":
        prewo = bool(request.form.get("preworkout"))
        protpo = bool(request.form.get("proteine_post"))
        creapo = bool(request.form.get("creatina_post"))
        q_pre = request.form.get("q_preworkout_pill") or ""
        q_prot = request.form.get("q_proteine_post_g") or ""
        q_crea = request.form.get("q_creatina_post_g") or ""

        petto = request.form.get("mis_petto") or ""
        vita  = request.form.get("mis_vita") or ""
        fianchi = request.form.get("mis_fianchi") or ""
        coscia = request.form.get("mis_coscia") or ""
        braccio = request.form.get("mis_braccio") or ""
        foto_url = ""
        file = request.files.get("foto")
        if file and file.filename and allowed_file(file.filename):
            fname = werkzeug.utils.secure_filename(f"{chosen_date.isoformat()}_{file.filename}")
            file.save(os.path.join(UPLOAD_DIR, fname))
            foto_url = f"{uploads_url(uid)}/{fname}"

        session = {
            "data": chosen_date.isoformat(),
            "giorno": request.form.get("giorno") or wd,
            "ex": [],
            "preworkout": prewo,
            "proteine_post": protpo,
            "creatina_post": creapo,
            "q_preworkout_pill": q_pre,
            "q_proteine_post_g": q_prot,
            "q_creatina_post_g": q_crea,
            "misure": {"petto":petto,"vita":vita,"fianchi":fianchi,"coscia":coscia,"braccio":braccio},
            "foto": foto_url,
            "completion": 0
        }

        selected_count = 0; done_count = 0

        # Piano del giorno
        for idx, ex in enumerate(plan_today):
            if request.form.get(f"plan_{idx}_use"):
                done = bool(request.form.get(f"plan_{idx}_done"))
                serie = request.form.get(f"plan_{idx}_serie") or ex["serie"]
                reps  = request.form.get(f"plan_{idx}_ripetizioni") or ex["ripetizioni"]
                load  = request.form.get(f"plan_{idx}_carico") or ""
                setdet= request.form.get(f"plan_{idx}_setdet") or ""
                diff  = request.form.get(f"plan_{idx}_diff") or ""
                session["ex"].append({
                    "esercizio": ex["esercizio"],
                    "serie": serie, "ripetizioni": reps, "carico": load,
                    "set_dettagli": setdet, "difficolta": diff,
                    "fatto": done
                })
                selected_count += 1
                if done: done_count += 1

        # Libreria
        lib_items = list(EXERCISE_LIBRARY.items())
        for cat_idx, (cat_name, items) in enumerate(lib_items):
            for i, item in enumerate(items):
                if request.form.get(f"lib_{cat_idx}_{i}_use"):
                    done = bool(request.form.get(f"lib_{cat_idx}_{i}_done"))
                    serie = request.form.get(f"lib_{cat_idx}_{i}_serie") or ""
                    reps  = request.form.get(f"lib_{cat_idx}_{i}_ripetizioni") or ""
                    load  = request.form.get(f"lib_{cat_idx}_{i}_carico") or ""
                    setdet= request.form.get(f"lib_{cat_idx}_{i}_setdet") or ""
                    diff  = request.form.get(f"lib_{cat_idx}_{i}_diff") or ""
                    session["ex"].append({
                        "esercizio": item["esercizio"],
                        "serie": serie, "ripetizioni": reps, "carico": load,
                        "set_dettagli": setdet, "difficolta": diff,
                        "fatto": done
                    })
                    selected_count += 1
                    if done: done_count += 1

        # Custom
        cust_idx = 0
        while True:
            name = request.form.get(f"cust_{cust_idx}_name")
            serie = request.form.get(f"cust_{cust_idx}_serie")
            reps  = request.form.get(f"cust_{cust_idx}_ripetizioni")
            load  = request.form.get(f"cust_{cust_idx}_carico")
            setdet= request.form.get(f"cust_{cust_idx}_setdet")
            diff  = request.form.get(f"cust_{cust_idx}_diff")
            done  = bool(request.form.get(f"cust_{cust_idx}_done"))
            if not any([name, serie, reps, load, setdet, diff, done]):
                break
            if name:
                session["ex"].append({
                    "esercizio": name, "serie": serie or "", "ripetizioni": reps or "", "carico": load or "",
                    "set_dettagli": setdet or "", "difficolta": (diff or ""), "fatto": done
                })
                selected_count += 1
                if done: done_count += 1
            cust_idx += 1

        session["completion"] = int(100 * (done_count / selected_count)) if selected_count else 0
        data["allenamenti"].append(session)

        # Sync diario (integratori per la stessa data)
        diary = None
        for r in data["giornaliero"]:
            if r.get("data") == chosen_date.isoformat():
                diary = r; break
        if diary is None:
            diary = {"data": chosen_date.isoformat(),
                     "creatina":False,"preworkout":False,"termogenico":False,"proteine":False,
                     "q_creatina_g":"","q_preworkout_pill":"","q_termogenico_pill":"","q_proteine_g":"",
                     "peso":"","vita":"","fianchi":"","note":""}
            data["giornaliero"].append(diary)
        if prewo:
            diary["preworkout"] = True
            diary["q_preworkout_pill"] = str(sum_float(diary.get("q_preworkout_pill")) + sum_float(q_pre))
        if protpo:
            diary["proteine"] = True
            diary["q_proteine_g"] = str(sum_float(diary.get("q_proteine_g")) + sum_float(q_prot))
        if creapo:
            diary["creatina"] = True
            diary["q_creatina_g"] = str(sum_float(diary.get("q_creatina_g")) + sum_float(q_crea))

        save_data(data, uid)
        return redirect(url_for("allenamenti", u=uid, date=chosen_date.isoformat()))

    records_day = [s for s in data.get("allenamenti", []) if s.get("data") == chosen_date.isoformat()]
    return render_template("allenamenti.html",
                           uid=uid, plan_today=plan_today, weekday=wd,
                           exercise_library=EXERCISE_LIBRARY,
                           records=records_day, chosen_date=chosen_date.isoformat())

# --------- ALIMENTAZIONE (GET/POST con target kcal del giorno) ---------
@app.route("/alimentazione", methods=["GET","POST"])
def alimentazione():
    uid = get_current_user()
    data = load_data(uid)
    chosen_date = get_date_from_request()
    wd = weekday_en(chosen_date)
    plan_type = data["meal_plan"].get(wd, "rest")

    goals = data.get("goals", {})
    base_kcal_target = goals.get("kcal_training") if plan_type=="training" else goals.get("kcal_rest")
    plan = DEFAULT_MEAL_PLAN["training" if plan_type=="training" else "rest"]

    existing = None
    for a in data.get("alimentazione", []):
        if a.get("data") == chosen_date.isoformat():
            existing = a; break

    if request.method == "POST":
        try:
            kcal_target_day = int(float(request.form.get("kcal_target") or base_kcal_target))
        except:
            kcal_target_day = int(base_kcal_target or plan["kcal_target"])

        kcal_tot = prot_tot = carb_tot = fat_tot = 0.0
        m = {
            "data": chosen_date.isoformat(),
            "plan_type": plan_type,
            "kcal_target": kcal_target_day,
            "meals": [],
            "kcal": 0, "proteine_g": 0, "carbo_g": 0, "grassi_g": 0,
            "creatina_mattino": bool(request.form.get("creatina_mattino")),
            "termogenico_mattino": bool(request.form.get("termogenico_mattino")),
            "proteine_pasto": bool(request.form.get("proteine_pasto")),
            "q_creatina_mattino_g": request.form.get("q_creatina_mattino_g") or "",
            "q_termogenico_mattino_pill": request.form.get("q_termogenico_mattino_pill") or "",
            "q_proteine_pasto_g": request.form.get("q_proteine_pasto_g") or "",
            "note": request.form.get("note") or "",
            "completion": 0
        }

        total_meals = len(plan["meals"]); consumed_count = 0

        for meal in plan["meals"]:
            key = meal["key"]
            consumed = bool(request.form.get(f"meal_{key}_done"))
            qty = request.form.get(f"meal_{key}_qty") or ""
            try: qty_num = float(qty)
            except: qty_num = 0.0

            base  = float(request.form.get(f"meal_{key}_base") or meal["base"])
            kcalB = float(request.form.get(f"meal_{key}_kcal_base") or 0)
            protB = float(request.form.get(f"meal_{key}_prot_base") or 0)
            carbB = float(request.form.get(f"meal_{key}_carb_base") or 0)
            fatB  = float(request.form.get(f"meal_{key}_fat_base") or 0)

            factor = (qty_num / base) if base else 0.0
            mk = round(factor * kcalB, 1)
            mp = round(factor * protB, 1)
            mc = round(factor * carbB, 1)
            mf = round(factor * fatB, 1)

            if consumed:
                consumed_count += 1
                kcal_tot += mk; prot_tot += mp; carb_tot += mc; fat_tot += mf

            m["meals"].append({
                "key": key, "label": meal["label"],
                "planned_qty": meal["planned_qty"], "unit": meal["unit"],
                "consumed": consumed, "consumed_qty": qty_num,
                "base": base, "kcal_base": kcalB, "prot_base": protB, "carb_base": carbB, "fat_base": fatB,
                "meal_kcal": mk, "meal_prot": mp, "meal_carb": mc, "meal_fat": mf
            })

        m["completion"] = int(100 * (consumed_count / total_meals)) if total_meals else 0
        m["kcal"] = round(kcal_tot, 0)
        m["proteine_g"] = round(prot_tot, 1)
        m["carbo_g"] = round(carb_tot, 1)
        m["grassi_g"] = round(fat_tot, 1)

        if existing:
            data["alimentazione"] = [x for x in data["alimentazione"] if x.get("data") != chosen_date.isoformat()]
        data["alimentazione"].append(m)

        # sync diario integratori (mattino/pasto)
        diary = None
        for r in data["giornaliero"]:
            if r.get("data") == chosen_date.isoformat():
                diary = r; break
        if diary is None:
            diary = {"data": chosen_date.isoformat(),
                     "creatina":False,"preworkout":False,"termogenico":False,"proteine":False,
                     "q_creatina_g":"","q_preworkout_pill":"","q_termogenico_pill":"","q_proteine_g":"",
                     "peso":"","vita":"","fianchi":"","note":""}
            data["giornaliero"].append(diary)

        if m["creatina_mattino"]:
            diary["creatina"] = True
            diary["q_creatina_g"] = str(sum_float(diary.get("q_creatina_g")) + sum_float(m["q_creatina_mattino_g"]))
        if m["proteine_pasto"]:
            diary["proteine"] = True
            diary["q_proteine_g"] = str(sum_float(diary.get("q_proteine_g")) + sum_float(m["q_proteine_pasto_g"]))
        if m["termogenico_mattino"]:
            diary["termogenico"] = True
            diary["q_termogenico_pill"] = str(sum_float(diary.get("q_termogenico_pill")) + sum_float(m["q_termogenico_mattino_pill"]))

        save_data(data, uid)
        return redirect(url_for("alimentazione", u=uid, date=chosen_date.isoformat()))

    records_day = [a for a in data.get("alimentazione", []) if a.get("data") == chosen_date.isoformat()]
    base_kcal_target = base_kcal_target or plan["kcal_target"]
    return render_template("alimentazione.html",
                           uid=uid, plan=plan, plan_type=plan_type,
                           plan_kcal_target=base_kcal_target,
                           records=records_day, chosen_date=chosen_date.isoformat())

# --------- PROGRESSI ---------
@app.route("/progressi")
def progressi():
    uid = get_current_user()
    data = load_data(uid)
    diario_records = data.get("giornaliero", [])
    try:
        diario_records = sorted(diario_records, key=lambda r: r["data"])
    except Exception:
        pass
    training_stats = compute_training_stats(data.get("allenamenti", []))
    return render_template("progressi.html", uid=uid, records=diario_records, training_stats=training_stats)

# --------- OBIETTIVI ---------
@app.route("/obiettivi", methods=["GET","POST"])
def obiettivi():
    uid = get_current_user()
    data = load_data(uid)
    goals = data.get("goals", {})
    if request.method == "POST":
        goals["kcal_training"] = float(request.form.get("kcal_training") or goals.get("kcal_training", 1700))
        goals["kcal_rest"]     = float(request.form.get("kcal_rest") or goals.get("kcal_rest", 1500))
        goals["weight_start"]  = float(request.form.get("weight_start") or goals.get("weight_start", 61.0))
        goals["weight_target"] = float(request.form.get("weight_target") or goals.get("weight_target", 55.0))
        w_curr = request.form.get("peso_attuale")
        if w_curr:
            try: goals["peso_attuale"] = float(w_curr)
            except: pass
        data["goals"] = goals
        save_data(data, uid)
        return redirect(url_for("obiettivi", u=uid))
    return render_template("obiettivi.html", uid=uid, goals=goals)


if __name__ == "__main__":
    # Avvio locale (su Render usare gunicorn con Procfile)
    app.run(debug=True, host="0.0.0.0", port=5000)

def obiettivi():
    uid = get_current_user()
    data = load_data(uid)
    goals = data.get("goals", {})
    if request.method == "POST":
        goals["kcal_training"] = float(request.form.get("kcal_training") or goals.get("kcal_training", 1700))
        goals["kcal_rest"]     = float(request.form.get("kcal_rest") or goals.get("kcal_rest", 1500))
        goals["weight_start"]  = float(request.form.get("weight_start") or goals.get("weight_start", 61.0))
        goals["weight_target"] = float(request.form.get("weight_target") or goals.get("weight_target", 55.0))
        w_curr = request.form.get("peso_attuale")
        if w_curr:
            try: goals["peso_attuale"] = float(w_curr)
            except: pass
        data["goals"] = goals
        save_data(data, uid)
        return redirect(url_for("obiettivi", u=uid))
    return render_template("obiettivi.html", uid=uid, goals=goals)


if __name__ == "__main__":
    # Avvio locale (su Render usare gunicorn con Procfile)
    app.run(debug=True, host="0.0.0.0", port=5000)
