import asyncio

import pytest

from alphaforge.execution.spot_clock import ClockBlocked, assess_sntp, check_host_clock


@pytest.mark.parametrize(
    "output",
    [
        "+0.462750 +/- 0.269760 time.apple.com 2a01:b740:a14:4000::22",
        "+0.050001 +/- 0.010000 time.apple.com 1.2.3.4",
        "-0.050001 +/- 0.010000 time.apple.com 1.2.3.4",
        "+0.001000 +/- 0.100001 time.apple.com 1.2.3.4",
        "timeout",
        "+nan +/- 0.0 time.apple.com 1.2.3.4",
    ],
)
def test_unverified_or_out_of_policy_clock_blocks(output):
    with pytest.raises(ClockBlocked):
        assess_sntp(output)


def test_clock_policy_boundary_and_no_adjustment_claim():
    result = assess_sntp("-0.050000 +/- 0.100000 time.apple.com 1.2.3.4")
    assert result["status"] == "HOST_CLOCK_SAMPLE_WITHIN_LIMITS"
    assert result["clock_adjusted"] is False
    assert result["authenticated_time_protocol"] is False


def test_clock_process_cancellation_kills_and_reaps_child(monkeypatch):
    class Process:
        returncode = None
        killed = False
        reaped = False

        async def communicate(self):
            raise asyncio.CancelledError()

        def kill(self):
            self.killed = True

        async def wait(self):
            self.reaped = True
            self.returncode = -9

    process = Process()

    async def spawn(*args, **kwargs):
        assert args == ("/usr/bin/sntp", "-t", "3", "-n", "1", "time.apple.com")
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(check_host_clock())
    assert process.killed and process.reaped
