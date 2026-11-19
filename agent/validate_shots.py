"""Plain-Python (no Blender, CPU only) check of a shots.json against the camrig contract.

Part of the local fork (branch `local`). Upstream had no validator; the contract was only prose in camera/README.md
and the code in camera/camrig.py. This follows both.

  python agent/validate_shots.py shots.json [--scene-info scene_info.json]

Checks: shot names unique and [a-z0-9_]; known move; key counts per move; t within 0..1 and ascending; pos and aim
present on the first key; orbit block; focus mode and rack keys; lens 8-800 mm; fstop range; handheld number or
{profile: walk}; res. With --scene-info (written by agent/inspect_scene.py --json) it also checks that every object
name resolves (exact, prefix, then case-insensitive substring, like camrig.find) and warns about positions far
outside the set. Exit code 1 if there are errors. Warnings do not fail.
"""
import json
import re
import sys

MOVES = {"static": 1, "dolly": 2, "truck": 2, "pedestal": 2, "push_in": 2, "crane": 2, "pan": 2, "tilt": 2,
         "orbit": 0, "dolly_zoom": 2, "path": 3}
FOCUS = {"none", "point", "track", "rack", "track_aim"}
ASPECTS = {"16:9", "1.85", "2.39"}
KNOWN_SHOT = {"name", "frames", "fps", "res", "aspect", "samples", "shutter", "sensor", "move", "ease", "keys",
              "focus", "fstop", "fstop_keys", "blades", "ratio", "handheld", "breathing", "lens_fx", "exposure",
              "orbit", "lens", "subject", "note"}


def resolve(name, names):
    if name in names:
        return True
    if any(n.startswith(name) for n in names):
        return True
    return any(name.lower() in n.lower() for n in names)


def vec(v):
    return isinstance(v, list) and len(v) == 3 and all(isinstance(x, (int, float)) for x in v)


def check(cfg, names=None, bounds=None):
    errs, warns = [], []
    if not isinstance(cfg.get("shots"), list) or not cfg["shots"]:
        return ["'shots' must be a non-empty list"], warns
    defaults = cfg.get("defaults", {})
    seen = set()
    for i, raw in enumerate(cfg["shots"]):
        s = dict(defaults)
        s.update(raw)
        n = s.get("name", f"#{i}")
        pre = f"shot {n}: "
        E = lambda m: errs.append(pre + m)  # noqa: E731
        W = lambda m: warns.append(pre + m)  # noqa: E731
        if not re.fullmatch(r"[a-z0-9_]+", str(s.get("name", ""))):
            E("name must be [a-z0-9_]")
        if n in seen:
            E("duplicate name")
        seen.add(n)
        for k in raw:
            if k not in KNOWN_SHOT:
                W(f"unknown field '{k}' (camrig ignores it)")
        mv = s.get("move", "static")
        if mv not in MOVES:
            E(f"unknown move '{mv}'")
            continue
        fr = s.get("frames", 120)
        if not isinstance(fr, int) or fr < 2:
            E("frames must be an int >= 2")
        keys = s.get("keys", [])
        if len(keys) < MOVES[mv]:
            E(f"move '{mv}' needs at least {MOVES[mv]} keys, has {len(keys)}")
        if mv == "orbit":
            o = s.get("orbit")
            if not isinstance(o, dict):
                E("orbit needs an 'orbit' block")
            else:
                if "center" not in o and "center_obj" not in o:
                    E("orbit needs center or center_obj")
                if "center" in o and not vec(o["center"]):
                    E("orbit.center must be [x,y,z]")
                if not isinstance(o.get("radius"), (int, float)) or o["radius"] <= 0:
                    E("orbit.radius must be > 0")
                if "center_obj" in o and names and not resolve(o["center_obj"], names):
                    E(f"orbit.center_obj '{o['center_obj']}' not in scene")
                span = abs(o.get("end_deg", 90) - o.get("start_deg", 0))
                if span > 180:
                    W(f"orbit sweeps {span} deg, may feel rushed")
        ts = [k.get("t", 0) for k in keys]
        if any(not 0 <= t <= 1 for t in ts) or ts != sorted(ts):
            E("key t values must be within 0..1 and ascending")
        for j, k in enumerate(keys):
            for f in ("pos", "aim"):
                if f in k and not vec(k[f]):
                    E(f"key {j} {f} must be [x,y,z]")
            for f in ("aim_obj", "pos_obj"):
                if f in k and names and not resolve(k[f], names):
                    E(f"key {j} {f} '{k[f]}' not in scene")
            if "lens" in k and not 8 <= k["lens"] <= 800:
                E(f"key {j} lens {k['lens']} outside 8..800 mm")
        if mv != "orbit" and keys:
            if "pos" not in keys[0] and "pos_obj" not in keys[0]:
                E("first key needs pos or pos_obj")
            if "aim" not in keys[0] and "aim_obj" not in keys[0] and mv != "dolly_zoom":
                E("first key needs aim or aim_obj")
        if mv in {"pan", "tilt"} and len({json.dumps(k.get("pos")) for k in keys if "pos" in k}) > 1:
            W("pan/tilt should keep pos constant")
        if bounds:
            lo, hi = bounds
            pad = max(hi[j] - lo[j] for j in range(3)) * 2
            pts = [k["pos"] for k in keys if "pos" in k and vec(k["pos"])]
            if mv == "orbit" and isinstance(s.get("orbit"), dict) and vec(s["orbit"].get("center")):
                pts.append(s["orbit"]["center"])
            for p in pts:
                if any(p[j] < lo[j] - pad or p[j] > hi[j] + pad for j in range(3)):
                    W(f"position {p} is far outside the set bounds {lo}..{hi}")
        fo = s.get("focus")
        if fo is not None:
            fm = fo.get("mode", "point")
            if fm not in FOCUS:
                E(f"unknown focus mode '{fm}'")
            if fm == "point" and "pos" not in fo and "obj" not in fo:
                E("focus point needs pos or obj")
            if fm == "track" and "obj" not in fo:
                E("focus track needs obj")
            if fm == "rack":
                fk = fo.get("keys", [])
                if len(fk) < 2:
                    E("focus rack needs at least 2 keys")
                for q in fk:
                    if "obj" not in q and "pos" not in q:
                        E("focus rack key needs obj or pos")
                    if "obj" in q and names and not resolve(q["obj"], names):
                        E(f"focus obj '{q['obj']}' not in scene")
            if fm in {"track", "point"} and "obj" in fo and names and not resolve(fo["obj"], names):
                E(f"focus obj '{fo['obj']}' not in scene")
        fs = s.get("fstop")
        if fs is not None and not 0.95 <= fs <= 64:
            E("fstop outside 0.95..64")
        hh = s.get("handheld", 0)
        if isinstance(hh, dict):
            if hh.get("profile") != "walk":
                E("handheld dict must have profile 'walk'")
            if mv == "path" and not 4 <= len(keys) <= 8:
                W("walk path: 4-6 keys recommended")
        elif not isinstance(hh, (int, float)) or not 0 <= hh <= 1:
            E("handheld must be 0..1 or {profile: walk}")
        if "aspect" in s and str(s["aspect"]) not in ASPECTS:
            W(f"aspect '{s['aspect']}' not one of {sorted(ASPECTS)}")
        if "res" in s and not (isinstance(s["res"], list) and len(s["res"]) == 2):
            E("res must be [w,h]")
    return errs, warns


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    cfg = json.load(open(sys.argv[1], encoding="utf-8"))
    names, bounds = None, None
    if "--scene-info" in sys.argv:
        info = json.load(open(sys.argv[sys.argv.index("--scene-info") + 1], encoding="utf-8"))
        names = set(info["all_object_names"])
        bounds = (info["set_min"], info["set_max"])
    errs, warns = check(cfg, names, bounds)
    for w in warns:
        print("WARN ", w)
    for e in errs:
        print("ERROR", e)
    print(f"{len(cfg.get('shots', []))} shots, {len(errs)} errors, {len(warns)} warnings")
    sys.exit(1 if errs else 0)


if __name__ == "__main__":
    main()
