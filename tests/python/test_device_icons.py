import unittest

from winsshui.device_icons import infer_device_icon, resolve_device_icon


class DeviceIconTests(unittest.TestCase):
    def test_infers_common_network_device_types(self) -> None:
        self.assertEqual("router", infer_device_icon("asus-router", "192.168.1.1"))
        self.assertEqual("switch", infer_device_icon("core-switch"))
        self.assertEqual("firewall", infer_device_icon("edge-pfsense"))
        self.assertEqual("nas", infer_device_icon("backup", group_name="Storage/NAS"))
        self.assertEqual("database", infer_device_icon("prod-db"))

    def test_explicit_icon_overrides_inference(self) -> None:
        self.assertEqual("terminal", resolve_device_icon("terminal", "asus-router"))
        self.assertEqual("router", resolve_device_icon(None, "asus-router"))
        self.assertEqual("server", resolve_device_icon("unknown", "app-01"))


if __name__ == "__main__":
    unittest.main()
