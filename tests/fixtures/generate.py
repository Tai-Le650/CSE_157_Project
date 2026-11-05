from __future__ import annotations

import math
from pathlib import Path

HERE = Path(__file__).resolve().parent
DT = 9614


def sample(i: int, n: int, gesture: str | None = "swipe_left") -> tuple[float, ...]:
    u = (i - n * 0.35) / (n * 0.3)
    bump = math.sin(math.pi * u) ** 2 if 0 <= u <= 1 else 0.0
    ax = 0.02 + 0.1 * bump + 0.003 * math.sin(i * 0.7)
    ay = -0.04 + (-0.5 if gesture == "swipe_left" else 0.5) * math.sin(2 * math.pi * u) * (1 if 0 <= u <= 1 else 0) + 0.003 * math.cos(i * 0.9)
    az = 0.99 + 0.004 * math.sin(i * 1.3)
    gx = 0.5 + 0.4 * math.sin(i * 0.5)
    gy = -1.2 + 0.4 * math.cos(i * 0.6)
    gz = (-180.0 if gesture == "swipe_left" else 180.0) * bump + 0.3 + 0.5 * math.sin(i * 1.1)
    if gesture is None:
        ay, gz = -0.04 + 0.003 * math.cos(i * 0.9), 0.3 + 0.5 * math.sin(i * 1.1)
    return ax, ay, az, gx, gy, gz


def fmt(values: tuple[float, ...], digits: int = 4) -> str:
    return ",".join(f"{v:.{digits}f}" for v in values)


def write(name: str, header: str, rows: list[str]) -> None:
    (HERE / name).write_text(header + "\n" + "\n".join(rows) + "\n", encoding="utf-8", newline="\n")


def stamps(n: int, start: int = 362_952_019) -> list[int]:
    return [start + i * DT for i in range(n)]


def main() -> None:
    n = 156
    t = stamps(n)
    rows = [f"{t[i]},{fmt(sample(i, n))}" for i in range(n)]
    write("trial_t_us.csv", "t_us,ax,ay,az,gx,gy,gz", rows)
    write("trial_time_us.csv", "time_us,ax,ay,az,gx,gy,gz", rows)
    write("trial_time_seconds.csv", "time,ax,ay,az,gx,gy,gz", [f"{(t[i] - t[0]) / 1e6:.6f},{fmt(sample(i, n))}" for i in range(n)])
    write("missing_column.csv", "t_us,ax,ay,az,gx,gy", [f"{t[i]},{fmt(sample(i, n)[:5])}" for i in range(20)])
    write("short.csv", "t_us,ax,ay,az,gx,gy,gz", rows[:12])

    n2 = 320
    t2 = stamps(n2)
    glitch_rows = []
    for i in range(n2):
        stamp = str(t2[i])
        if i in (120, 240):
            stamp = stamp[3:]
        glitch_rows.append(f"{stamp},{fmt(sample(i, n2))}")
    write("glitch.csv", "time_us,ax,ay,az,gx,gy,gz", glitch_rows)

    start = (1 << 32) - 60 * DT
    write("wrap.csv", "t_us,ax,ay,az,gx,gy,gz", [f"{(start + i * DT) % (1 << 32)},{fmt(sample(i, 150, None))}" for i in range(150)])

    first = stamps(100, 50_000_000)
    second = stamps(100, 1_000_000)
    write("reset.csv", "t_us,ax,ay,az,gx,gy,gz", [f"{s},{fmt(sample(i, 100, None))}" for i, s in enumerate(first + second)])

    dup = stamps(120)
    dup_rows = [f"{dup[i]},{fmt(sample(i, 120, None))}" for i in range(120)]
    for index in (90, 60, 30):
        dup_rows.insert(index, f"{dup[index - 1]},{fmt(sample(index, 120, None))}")
    write("duplicates.csv", "t_us,ax,ay,az,gx,gy,gz", dup_rows)

    gap_t = stamps(200)
    del gap_t[150:163]
    del gap_t[50]
    del gap_t[80]
    write("gaps.csv", "t_us,ax,ay,az,gx,gy,gz", [f"{s},{fmt(sample(i, 200, None))}" for i, s in enumerate(gap_t)])

    bad = [f"{t[i]},{fmt(sample(i, n))}" for i in range(80)]
    bad[10] = f"{t[10]},nan,0.1,0.9,1,2,3"
    bad[20] = f"{t[20]},0.1,inf,0.9,1,2,3"
    bad[30] = f"{t[30]},0.1,,0.9,1,2,3"
    bad[40] = f"{t[40]},0.1,abc,0.9,1,2,3"
    bad[50] = f"{t[50]},0.1,0.2"
    write("bad_values.csv", "t_us,ax,ay,az,gx,gy,gz", bad)

    cli = stamps(94, 5_000_000)
    write("idle_0001.csv", "t_us,ax,ay,az,gx,gy,gz", [f"{s},{fmt(sample(i, 94, None), 3)}" for i, s in enumerate(cli)])
    write("swipe_left_0001.csv", "t_us,ax,ay,az,gx,gy,gz", [f"{s},{fmt(sample(i, 94), 3)}" for i, s in enumerate(cli)])


if __name__ == "__main__":
    main()
