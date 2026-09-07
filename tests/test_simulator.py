import unittest
from datetime import datetime

from simulator.simulator import (
    CAMPUS_INFRASTRUCTURE,
    create_meters,
    generate_reading,
    calculate_building_power,
)


class TestSimulator(unittest.TestCase):
    def test_meter_registry_has_42_meters(self):
        meters = create_meters()
        self.assertEqual(len(meters), 42)
        self.assertEqual(meters[0]["meter_id"], "M001")
        self.assertEqual(meters[0]["building_id"], "BH1")
        self.assertEqual(meters[0]["building_type"], "Hostels")
        self.assertEqual(meters[-1]["meter_id"], "M042")
        self.assertEqual(meters[-1]["building_id"], "OAT")
        self.assertEqual(meters[-1]["building_type"], "Facilities")

    def test_campus_infrastructure_categories(self):
        expected_categories = {"Hostels", "Departments", "Lecture Theatres", "Facilities"}
        self.assertEqual(set(CAMPUS_INFRASTRUCTURE.keys()), expected_categories)

    def test_calculate_building_power_positive(self):
        dt = datetime(2026, 9, 7, 14, 0)
        power = calculate_building_power("BH1", "Hostels", dt)
        self.assertGreater(power, 0)

        power_dept = calculate_building_power("CS", "Departments", dt)
        self.assertGreater(power_dept, 0)

    def test_generate_reading_electrical_parameters(self):
        meters = create_meters()
        dt = datetime(2026, 9, 7, 14, 0)
        reading = generate_reading(meters[0], event_id=1, dt=dt)

        self.assertEqual(reading["meter_id"], "M001")
        self.assertEqual(reading["building_id"], "BH1")
        self.assertGreater(reading["power_kw"], 0)
        self.assertGreater(reading["voltage_v"], 180)
        self.assertLess(reading["voltage_v"], 270)
        self.assertGreater(reading["current_a"], 0)
        self.assertGreaterEqual(reading["power_factor"], 0.70)
        self.assertLessEqual(reading["power_factor"], 1.0)


if __name__ == "__main__":
    unittest.main()
