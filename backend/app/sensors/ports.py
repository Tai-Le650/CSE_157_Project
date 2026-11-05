from __future__ import annotations

from serial.tools import list_ports


def list_serial_ports() -> list[dict]:
    ports = []
    for info in sorted(list_ports.comports(), key=lambda p: p.device):
        ports.append({
            "device": info.device,
            "description": info.description or "",
            "hwid": info.hwid or "",
            "vid": f"{info.vid:04X}" if info.vid is not None else None,
            "pid": f"{info.pid:04X}" if info.pid is not None else None,
            "serial_number": info.serial_number,
            "manufacturer": info.manufacturer,
        })
    return ports
