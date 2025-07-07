import datetime
import logging
from typing import Any

from pmk_probes._data_structures import PMKMetadata, PowerOverFiberMetadata, FireFlyMetadata


def test_normal_metadata() -> None:
    today = datetime.datetime.now()
    metadata = PMKMetadata(
        eeprom_layout_revision="1.2",
        serial_number=f"{today.strftime('%m%y')}{100:03d}",
        manufacturer="http://www.pmk.de",
        model="PowerOverFiber",
        description="Optically isolated power supply",
        production_date=today.date(),
        calibration_due_date=(today + datetime.timedelta(days=365)).date(),
        calibration_instance="PMK",
        hardware_revision="M0.00 BM0.03 LM0.01",
        software_revision="BM v0.0.0 LM v0.0.0",
        uuid="886-102-514"
    )


def test_due_date_none() -> None:
    today = datetime.datetime.now()
    constructor_kwargs: dict[type[PMKMetadata | PowerOverFiberMetadata | FireFlyMetadata], dict[str, Any]] = {
        PMKMetadata: {},
        PowerOverFiberMetadata: {},
        FireFlyMetadata: {"propagation_delay": 10.0},
    }
    for constructor, kwargs in constructor_kwargs.items():
        metadata = constructor(
            eeprom_layout_revision="1.2",
            serial_number=f"{today.strftime('%m%y')}{100:03d}",
            manufacturer="http://www.pmk.de",
            model="PowerOverFiber",
            description="Optically isolated power supply",
            production_date=today.date(),
            calibration_due_date=None,
            calibration_instance="PMK",
            hardware_revision="M0.00 BM0.03 LM0.01",
            software_revision="BM v0.0.0 LM v0.0.0",
            uuid="886-102-514",
            **kwargs
        )
        logging.info(metadata.to_bytes())
