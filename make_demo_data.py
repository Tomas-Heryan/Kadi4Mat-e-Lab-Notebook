"""Generate small SYNTHETIC demo files for the photocatalysis demo project.

The numbers are made up (deterministic pseudo-random) and only serve to exercise the
file upload, checksum verification and RO-Crate export paths. Re-running produces
byte-identical files.
"""
from __future__ import annotations

import math
import random
from pathlib import Path

HERE = Path(__file__).parent
rng = random.Random(20260805)


def write(name: str, text: str) -> None:
    (HERE / name).write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {name} ({len(text)} chars)")


# 1. XRD pattern of an anatase-like powder (synthetic peaks on a background)
peaks = [(25.3, 100), (37.8, 20), (48.0, 30), (53.9, 18), (55.1, 18), (62.7, 14), (68.8, 6), (70.3, 6), (75.0, 10)]
lines = ["# SYNTHETIC demo data - XRD, Cu Ka, 2theta [deg], intensity [counts]", "2theta,intensity"]
two_theta = 10.0
while two_theta <= 80.0 + 1e-9:
    intensity = 40 + 10 * math.exp(-(two_theta - 10) / 30)
    for pos, height in peaks:
        intensity += height * 12 * math.exp(-((two_theta - pos) ** 2) / (2 * 0.18 ** 2))
    intensity += rng.gauss(0, 2.5)
    lines.append(f"{two_theta:.2f},{max(intensity, 0):.1f}")
    two_theta += 0.02
write("xrd_tio2-sg-2026-001-c450.xy", "\n".join(lines) + "\n")

# 2. LC-MS/MS quantitative results of the photocatalytic run aliquots
analytes = {"diclofenac": 1.80, "carbamazepine": 0.95, "sulfamethoxazole": 0.62, "ibuprofen": 2.40}
rows = ["# SYNTHETIC demo data - LC-MS/MS results, concentrations in ug/L",
        "sample_id,analyte,concentration_ug_L,loq_ug_L,qc_flag"]
for t, factor in ((0, 1.0), (60, 0.42), (120, 0.11)):
    for analyte, c0 in analytes.items():
        c = c0 * factor * (1 + rng.gauss(0, 0.03))
        loq = 0.05
        flag = "ok" if c >= loq else "<LOQ"
        rows.append(f"PHOTOCAT-R01-T{t:03d},{analyte},{c:.3f},{loq},{flag}")
write("lcms_pharma_2026-08-05_s01_results.csv", "\n".join(rows) + "\n")

# 3. Power analyser log of the photoreactor (1 Hz, 2 h)
rows = ["# SYNTHETIC demo data - Yokogawa WT310E log, 1 s interval", "time_s,voltage_V,current_A,active_power_W,energy_Wh"]
energy = 0.0
for t in range(0, 7200):
    on = t >= 300  # lamp switched on after 5 min dark phase
    p = (96.5 + rng.gauss(0, 0.8)) if on else (4.2 + rng.gauss(0, 0.1))
    v = 230.0 + rng.gauss(0, 0.6)
    i = p / (v * 0.97)
    energy += p / 3600
    rows.append(f"{t},{v:.1f},{i:.3f},{p:.1f},{energy:.3f}")
write("power_photoreactor_r01_2026-08-05.csv", "\n".join(rows) + "\n")

# 4. BET report (text)
write("bet_tio2-sg-2026-001-c450_report.txt", """SYNTHETIC demo data - gas physisorption report
Instrument: Micromeritics 3Flex   Adsorptive: N2 at 77 K
Sample: TIO2-SG-2026-001-C450     Mass after degassing: 112.4 mg
Degassing: 200 degC, 6 h, vacuum
BET surface area: 58.3 m2/g  (p/p0 0.05-0.30, C = 112)
Total pore volume (p/p0 = 0.99): 0.214 cm3/g
BJH desorption mean pore diameter: 11.6 nm
Isotherm type: IV(a), H2(b) hysteresis
""")

# 5. Photocatalytic kinetics evaluation table
rows = ["# SYNTHETIC demo data - pseudo-first-order fit of ln(C0/C) vs t",
        "analyte,k_app_1_per_min,half_life_min,r2,removal_120min_percent"]
for analyte, c0 in analytes.items():
    k = 0.0184 * (1 + rng.gauss(0, 0.05))
    rows.append(f"{analyte},{k:.4f},{math.log(2) / k:.1f},{0.98 + rng.random() * 0.015:.3f},{(1 - 0.11) * 100:.1f}")
write("photocat_r01_kinetics.csv", "\n".join(rows) + "\n")
