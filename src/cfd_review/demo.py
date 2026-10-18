"""Small mathematical meshes, intentionally unrelated to any team vehicle.

These values are not CFD, measurements, or predictions of aerodynamic benefit.
"""
from __future__ import annotations

import math
from .report import project_from_cases


def _wing(name: str, angle: float, offset: float, chord: float) -> dict:
    positions, values, indices = [], [], []
    rings, stations = 48, 8
    theta = math.radians(angle)
    for j in range(stations + 1):
        span = .64 * j / stations
        for i in range(rings):
            a = 2 * math.pi * i / rings
            x = chord * .5 * (1 - math.cos(a))
            z = .065 * chord * math.sin(a) * (1 - .45 * x / chord)
            positions += [offset + x * math.cos(theta) - z * math.sin(theta), span,
                          .38 + x * math.sin(theta) + z * math.cos(theta)]
            values.append(round(-1.45 * math.sin(a) * math.exp(-((x/chord-.3)/.4)**2) * (1-.35*(span/.64)**2) - angle*.012, 6))
    for j in range(stations):
        for i in range(rings):
            a, b = j*rings+i, j*rings+(i+1) % rings
            c, d = a+rings, b+rings
            indices += [a, b, d, a, d, c]
    # Close the two span ends with source-local triangle fans.
    for j in [0, stations]:
        for i in range(1, rings-1):
            a, b, c = j*rings, j*rings+i, j*rings+i+1
            indices += [a, c, b] if j == 0 else [a, b, c]
    return {"id": name, "name": name.replace("-", " ").title(), "positions": positions, "indices": indices, "cp": values}


def _box() -> dict:
    p = [-.12,0,.18, 1.38,0,.18, 1.38,.72,.18, -.12,.72,.18,
         -.12,0,.22, 1.38,0,.22, 1.38,.72,.22, -.12,.72,.22]
    ix = [0,2,1,0,3,2,4,5,6,4,6,7,0,1,5,0,5,4,1,2,6,1,6,5,2,3,7,2,7,6,3,0,4,3,4,7]
    return {"id": "reference-plate", "name": "Reference plate", "positions": p, "indices": ix, "cp": [.05,.1,.15,.1,-.2,-.3,-.25,-.1]}


def _section(x: float, variant: int) -> dict:
    positions, cp, cpt, indices = [], [], [], []
    ny, nz = 16, 16
    for k in range(nz+1):
        z = -.02 + .95*k/nz
        for j in range(ny+1):
            y = .9*j/ny
            wake = math.exp(-((y-(.45+.035*variant*math.sin(x*3)))/.17)**2-((z-.44)/.16)**2)
            strength = .55*(.5+.5*math.tanh((x-.15)*3))*(1+.12*variant)
            positions += [round(x, 7), round(y, 7), round(z, 7)]
            cp.append(round(-.85*math.exp(-((z-.35)/.18)**2)*math.cos(x*2.5)*(1-.5*y)+.09*variant, 6))
            cpt.append(round(1-strength*wake, 6))
    for k in range(nz):
        for j in range(ny):
            a = k*(ny+1)+j
            indices += [a,a+1,a+ny+2,a,a+ny+2,a+ny+1]
    return {"x": x, "positions": positions, "indices": indices, "cp": cp, "cpt": cpt}


def _tube(variant: int) -> dict:
    positions, indices, values = [], [], []
    steps, ring = 48, 12
    for i in range(steps+1):
        u = i/steps
        x = .2+1.9*u
        y = .5+.055*math.sin(u*9+variant*.2)
        z = .43+.065*math.cos(u*8+variant*.3)
        r = (.028+.035*u)*(1+.15*variant)
        for j in range(ring):
            a = 2*math.pi*j/ring
            positions += [x, y+r*math.cos(a), z+r*math.sin(a)]
            values.append(round(1-u*.65+.12*math.sin(a), 6))
    for i in range(steps):
        for j in range(ring):
            a, b = i*ring+j, i*ring+(j+1)%ring
            indices += [a,b,b+ring,a,b+ring,a+ring]
    return {"id": "synthetic-vortex", "name": "Synthetic vortex shape", "kind": "isosurface",
            "positions": positions, "indices": indices, "values": values, "field": "DemoScalar",
            "units": "", "colorRange": [0, 1.2], "opacity": .8, "visible": True,
            "criterion": "Mathematical tube; not a computed Q or lambda2 isosurface"}


def make_demo_case(variant: int = 0) -> dict:
    count = 11 if variant == 0 else 9
    return {"schema": "cfd-review-case", "version": 1,
            "id": f"synthetic-{'a' if variant == 0 else 'b'}", "name": f"DEMO {'A · Baseline' if variant == 0 else 'B · Variant'}",
            "data": {"meta": {"title": "Synthetic airfoil assembly", "source": "Procedural geometry and mathematical scalars; not CFD or experimental results",
                               "sourceKey": f"synthetic-airfoil-{variant}-v1", "units": "m", "axis": {"up": "z"},
                               "isDemo": True, "halfCar": True, "mirrorAxis": "y", "scalarMirror": True,
                               "ranges": {"Cp": [-2, 1], "CpT": [.2, 1]}, "surfaceRange": [-2, 1],
                               "sectionOpacity": .55, "cptNearOneTransparent": True,
                               "coefficientReference": {"definition": "Mathematical demo values; no physical coefficient reference"}},
                     "parts": [_wing("main-airfoil", -4-3*variant, 0, .95), _wing("rear-element", -12-4*variant, .78, .45), _box()],
                     "sections": [_section(round(-.25+2.35*i/(count-1), 7), variant) for i in range(count)],
                     "layers": [_tube(variant)]}}


def make_demo_project() -> dict:
    return project_from_cases([make_demo_case(0), make_demo_case(1)], "Synthetic airfoil comparison")
