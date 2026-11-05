from __future__ import annotations

from app.sensors.protocol import LineAssembler, parse_line


def test_header_aliases():
    assert parse_line(b"t_us,ax,ay,az,gx,gy,gz").alias == "t_us"
    assert parse_line(b"time_us,ax,ay,az,gx,gy,gz\r").alias == "time_us"
    assert parse_line("TIME_US, ax, ay, az, gx, gy, gz").kind == "header"


def test_sample_line():
    parsed = parse_line(b"368519081,0.3876,-0.0922,0.8777,19.425,28.8925,-157.605\r")
    assert parsed.kind == "sample"
    assert parsed.t_raw == 368519081
    assert parsed.values == (0.3876, -0.0922, 0.8777, 19.425, 28.8925, -157.605)


def test_diagnostics_and_errors():
    error = parse_line(b"ERROR: IMU initialization failed")
    assert error.kind == "diagnostic" and error.is_error
    info = parse_line(b"IMU initialized!")
    assert info.kind == "diagnostic" and not info.is_error


def test_malformed_lines():
    assert parse_line(b"123,1,2,3").reason == "field_count"
    assert parse_line(b"123,1,2,x,4,5,6").reason == "non_numeric"
    assert parse_line(b"123,nan,2,3,4,5,6").reason == "non_finite"
    assert parse_line(b"123,inf,2,3,4,5,6").reason == "non_finite"
    assert parse_line(b"-5,1,2,3,4,5,6").reason == "bad_timestamp"
    assert parse_line(b"12.5,1,2,3,4,5,6").reason == "bad_timestamp"
    assert parse_line(b"").kind == "empty"


def test_assembler_drops_partial_first_line_and_joins_chunks():
    asm = LineAssembler()
    assert asm.feed(b"9,0.1,0.2,0.3,1,2,3\n100,0.1,0.2") == []
    assert asm.partial_dropped == 1
    lines = asm.feed(b",0.3,1,2,3\n200,0.1,0.2,0.3,1,2,3\n")
    assert lines == [b"100,0.1,0.2,0.3,1,2,3", b"200,0.1,0.2,0.3,1,2,3"]


def test_assembler_keeps_header_as_first_line():
    asm = LineAssembler()
    assert asm.feed(b"t_us,ax,ay,az,gx,gy,gz\n1,0,0,1,0,0,0\n") == [b"t_us,ax,ay,az,gx,gy,gz", b"1,0,0,1,0,0,0"]
    assert asm.partial_dropped == 0


def test_assembler_overflow_resyncs():
    asm = LineAssembler(sync_first_line=False, max_line_bytes=32)
    assert asm.feed(b"x" * 40) == []
    assert asm.overflows == 1
    assert asm.feed(b"tail\n5,0,0,1,0,0,0\n") == [b"5,0,0,1,0,0,0"]
