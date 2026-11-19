"""Print what a Claude "director" needs to know about a .blend before writing shots.json.

PRINTS ONLY: no render, no save, no GPU work. Part of the local fork (branch `local`); replaces the survey step the
paid API director did.

  blender -b <scene.blend> --factory-startup --python agent/inspect_scene.py -- [--json out.json] [--top 25]

Prints: scene, engine, units, fps, world, set bounds and floor height, every camera (and the active one), lights,
the biggest objects with centre and size, linked libraries and missing images. --json also writes it all to a file
(used by agent/validate_shots.py --scene-info to check that object names in shots.json exist).
"""
import json
import sys

import bpy
from mathutils import Vector

MESHY = {"MESH", "CURVE", "FONT", "SURFACE", "META", "VOLUME"}


def argv():
    a = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    out = {"json": None, "top": 25}
    i = 0
    while i < len(a):
        if a[i] == "--json":
            out["json"] = a[i + 1]
            i += 2
        elif a[i] == "--top":
            out["top"] = int(a[i + 1])
            i += 2
        else:
            i += 1
    return out


def bounds(root):
    """World-space (min, max) of an object and its mesh descendants (same rule as camrig.bounds)."""
    pts = []
    for o in [root, *root.children_recursive]:
        if o.type in MESHY:
            pts += [o.matrix_world @ Vector(c) for c in o.bound_box]
    if not pts:
        p = root.matrix_world.translation.copy()
        return p, p
    lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    return lo, hi


def v3(v):
    return [round(v[0], 3), round(v[1], 3), round(v[2], 3)]


def missing_images():
    out = []
    for im in bpy.data.images:
        if im.source == "FILE" and not im.packed_file and im.size[0] == 0:
            out.append(im.name)
    return out


def main():
    opt = argv()
    sc = bpy.context.scene
    info = {
        "file": bpy.data.filepath,
        "scene": sc.name,
        "scenes_in_file": [s.name for s in bpy.data.scenes],
        "engine": sc.render.engine,
        "unit_system": sc.unit_settings.system,
        "unit_scale": sc.unit_settings.scale_length,
        "fps": sc.render.fps,
        "frame_range": [sc.frame_start, sc.frame_end],
        "resolution": [sc.render.resolution_x, sc.render.resolution_y],
        "active_camera": sc.camera.name if sc.camera else None,
        "world": sc.world.name if sc.world else None,
    }
    cams, lights, objs = [], [], []
    allmin = Vector((1e9, 1e9, 1e9))
    allmax = Vector((-1e9, -1e9, -1e9))
    nmesh = 0
    for o in sc.objects:
        if o.type == "CAMERA":
            cams.append({"name": o.name, "pos": v3(o.matrix_world.translation), "lens": round(o.data.lens, 1),
                         "sensor": round(o.data.sensor_width, 2), "animated": bool(o.animation_data)})
        elif o.type == "LIGHT":
            lights.append({"name": o.name, "type": o.data.type, "energy": round(o.data.energy, 1),
                           "pos": v3(o.matrix_world.translation)})
        elif o.type in MESHY:
            if o.type == "MESH":
                nmesh += 1
                for c in o.bound_box:
                    w = o.matrix_world @ Vector(c)
                    allmin = Vector((min(allmin[0], w[0]), min(allmin[1], w[1]), min(allmin[2], w[2])))
                    allmax = Vector((max(allmax[0], w[0]), max(allmax[1], w[1]), max(allmax[2], w[2])))
            # root-most mesh objects only, so a GLB import root is one entry (children are included in its bounds)
            if o.parent is None or o.parent.type not in MESHY:
                lo, hi = bounds(o)
                objs.append({"name": o.name, "type": o.type, "center": v3((lo + hi) / 2), "size": v3(hi - lo)})
    info["set_min"], info["set_max"] = v3(allmin), v3(allmax)
    info["set_size"] = v3(allmax - allmin)
    info["floor_z"] = round(allmin[2], 3)
    info["mesh_object_count"] = nmesh
    info["cameras"], info["lights"] = cams, lights
    objs.sort(key=lambda d: -(d["size"][0] * d["size"][1] * d["size"][2]))
    info["objects_top"] = objs[: opt["top"]]
    info["all_object_names"] = sorted(o.name for o in bpy.data.objects)
    info["libraries"] = [lib.filepath for lib in bpy.data.libraries]
    info["missing_images"] = missing_images()

    print("=== anyshot inspect ===")
    for k in ("file", "scene", "scenes_in_file", "engine", "unit_system", "unit_scale", "fps", "frame_range",
              "resolution", "active_camera", "world", "set_min", "set_max", "set_size", "floor_z",
              "mesh_object_count", "libraries", "missing_images"):
        print(f"{k:18s} {info[k]}")
    sz = info["set_size"]
    print(f"{'scale':18s} height {sz[2]:.1f} m, footprint {sz[0]:.1f} x {sz[1]:.1f} m "
          f"(a person is 1.7 m: height = {sz[2] / 1.7:.0f} people)")
    print(f"--- cameras ({len(cams)}) ---")
    for c in cams:
        print(" ", c)
    print(f"--- lights ({len(lights)}) ---")
    for lt in lights[:20]:
        print(" ", lt)
    print(f"--- biggest {len(info['objects_top'])} objects (name, centre, size in m) ---")
    for d in info["objects_top"]:
        print(f"  {d['name']:40s} centre {d['center']}  size {d['size']}")
    if opt["json"]:
        with open(opt["json"], "w", encoding="utf-8") as f:
            json.dump(info, f, indent=1)
        print("wrote", opt["json"])


main()
