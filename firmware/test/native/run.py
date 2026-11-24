"""Compila e exercita o firmware real com I/O simulado, sem dependências Python."""
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory

firmware = Path(__file__).resolve().parents[2]
native = firmware / "test" / "native"
with TemporaryDirectory(prefix="dilatation-firmware-") as directory:
    temporary = Path(directory)
    common = ["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror"]
    pure = temporary / "acquisition"
    subprocess.run([*common, f"-I{firmware / 'include'}", str(native / "test_acquisition.cpp"),
                    "-o", str(pure)], check=True)
    subprocess.run([str(pure)], check=True)
    for variant in ("default", "ntc_raw", "calibrated"):
        config = (firmware / "include" / "config.h").read_text()
        if variant != "default":
            config = config.replace("NTC_ENABLED = false", "NTC_ENABLED = true")
        if variant == "calibrated":
            for original, replacement in {
                "NTC_MODEL_ENABLED = false": "NTC_MODEL_ENABLED = true",
                "DISPLACEMENT_ENABLED = false": "DISPLACEMENT_ENABLED = true",
                "SERIES_OHMS = 0.0f": "SERIES_OHMS = 10000.0f",
                "NTC_R0_OHMS = 0.0f": "NTC_R0_OHMS = 10000.0f",
                "NTC_BETA_K = 0.0f": "NTC_BETA_K = 3950.0f",
                "MM_PER_COUNT = 0.0f": "MM_PER_COUNT = 0.001f",
            }.items():
                config = config.replace(original, replacement)
        (temporary / "config.h").write_text(config)
        executable = temporary / variant
        subprocess.run([*common, f"-I{temporary}", f"-I{native / 'fakes'}",
                        f"-I{firmware / 'include'}", str(native / "test_firmware.cpp"),
                        "-o", str(executable)], check=True)
        for scenario in ("normal", "timeout", "rail", "ntc_rail", "tare", "tare_failure",
                         "tare_busy", "pause", "wrap", "skew"):
            subprocess.run([str(executable), scenario], check=True)
        print(f"{variant}: 10 cenários aprovados")
print("Conversões e 30 cenários do firmware aprovados. I/O simulado não valida hardware.")
