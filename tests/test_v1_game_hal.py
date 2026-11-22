import unittest

from ports import amoled_v1
from ports import v1_game_hal as hal


class Bus:
    def __init__(self):
        self.addresses = {0x18, 0x20, 0x34, 0x38, 0x51, 0x6B}
        self.data = {
            (0x34, 0x03): b"\x4a",
            (0x51, 0x00): b"\x00",
            (0x51, 0x04): b"\x59\x00\x14\x22\x00\x11\x26",
            (0x6B, 0): b"\x05",
        }
        self.calls = []

    def scan(self):
        self.calls.append("scan")
        return self.addresses

    def readfrom_mem(self, address, reg, n):
        self.calls.append((address, reg, n))
        try:
            return self.data[address, reg]
        except KeyError:
            raise OSError("unreadable")

    def writeto_mem(self, *args):
        raise AssertionError("preflight must be read-only")


class NativeAPI:
    class QSPIPanel:
        pass

    class AMOLED:
        pass


class V1GameHALTest(unittest.TestCase):
    def test_unconfirmed_is_rejected_before_i2c(self):
        bus = Bus()
        with self.assertRaisesRegex(hal.GameHALUnavailable, "physical"):
            hal.probe(bus)
        self.assertEqual(bus.calls, [])

    def test_v2_and_unsettled_touch_are_rejected_without_register_access(self):
        for address in (0x15, 0x38):
            with self.subTest(address=address):
                bus = Bus()
                bus.addresses.symmetric_difference_update({address})
                with self.assertRaises(amoled_v1.BoardMismatch):
                    hal.probe(bus, confirmed_v1=True)
                self.assertEqual(bus.calls, ["scan"])

    def test_valid_presence_is_not_production_readiness(self):
        report = hal.probe(Bus(), confirmed_v1=True, native_module=NativeAPI)
        self.assertEqual(report, {
            "board": "amoled_1_8_v1", "touch_present": True,
            "native_display_api_present": True, "imu_addr": 0x6B,
            "rtc": "valid", "pmu_identified": True, "audio_codec_present": True,
        })
        with self.assertRaisesRegex(hal.GameHALUnavailable, "audio not tested"):
            hal.require_game_hal(report)
        hal.require_game_hal(report, display_touch_tested=True, audio_tested=True,
                             rtc_read_only_in_game=True)

    def test_diagnostics_still_work_when_clock_is_unavailable(self):
        for change, status in (
            (None, "unreadable"),
            (b"\x80\0\0\0\0\0\0", "unset"),
            (b"\0\0\0\x31\0\x02\x27", "invalid"),
            (b"\0\0\0\x01\0\x02\x23", "stale"),
        ):
            with self.subTest(status=status):
                bus = Bus()
                if change is None:
                    del bus.data[0x51, 0x04]
                else:
                    bus.data[0x51, 0x04] = change
                report = hal.probe(bus, confirmed_v1=True)
                self.assertEqual(report["rtc"], status)
                self.assertEqual(report["imu_addr"], 0x6B)
                with self.assertRaisesRegex(hal.GameHALUnavailable, "PCF85063A"):
                    hal.require_game_hal(report)
        bus = Bus()
        bus.addresses.remove(0x51)
        report = hal.probe(bus, confirmed_v1=True)
        self.assertEqual(report["rtc"], "missing")
        self.assertNotIn((0x51, 0x04, 7), bus.calls)

    def test_clock_mode_is_checked_without_reconfiguration(self):
        for control, status in ((0x20, "stopped"), (0x02, "unsupported_mode"),
                                (0x80, "unsupported_mode")):
            with self.subTest(control=control):
                bus = Bus()
                bus.data[0x51, 0] = bytes((control,))
                self.assertEqual(hal.probe(bus, confirmed_v1=True)["rtc"], status)
                self.assertNotIn((0x51, 0x04, 7), bus.calls)

    def test_wrong_or_duplicate_imu_identity_is_not_accepted(self):
        bus = Bus()
        bus.data[0x6B, 0] = b"\x00"
        self.assertIsNone(hal.probe(bus, confirmed_v1=True)["imu_addr"])
        bus.addresses.add(0x6A)
        bus.data[0x6A, 0] = b"\x05"
        self.assertEqual(hal.probe(bus, confirmed_v1=True)["imu_addr"], 0x6A)
        bus.data[0x6B, 0] = b"\x05"
        self.assertIsNone(hal.probe(bus, confirmed_v1=True)["imu_addr"])


if __name__ == "__main__":
    unittest.main()
