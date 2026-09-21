"""Biomass to carbon to CO2-equivalent.

Both conversions are fixed physical/inventory constants, not fitted values, so
the uncertainty on a carbon figure is inherited entirely from the biomass
estimate beneath it. That is why the carbon interval is the biomass interval
scaled by the same factors.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

#: IPCC 2006 Guidelines, Vol.4 Ch.4, Table 4.3 — default carbon fraction of
#: aboveground dry matter for tropical and temperate forest.
CARBON_FRACTION = 0.47

#: Molecular weight ratio CO2 : C = 44.01 / 12.011
CO2E_PER_CARBON = 44.01 / 12.011

#: IPCC default root-to-shoot ratio for closed broadleaf forest, used only when
#: belowground biomass is explicitly requested. Reported separately, never
#: silently folded into the aboveground figure.
ROOT_TO_SHOOT = 0.24


@dataclass
class CarbonResult:
    carbon_mean: float               # tC/ha
    carbon_p05: float
    carbon_p95: float
    co2e_mean: float                 # tCO2e/ha
    co2e_p05: float
    co2e_p95: float
    total_carbon_t: float            # tC over the whole AOI
    total_co2e_t: float              # tCO2e over the whole AOI
    carbon_grid: np.ndarray          # tC/ha per cell
    belowground_carbon_mean: float   # tC/ha, reported separately

    def as_dict(self) -> dict[str, Any]:
        return {
            "carbon": {
                "mean_tc_ha": round(self.carbon_mean, 2),
                "p05_tc_ha": round(self.carbon_p05, 2),
                "p95_tc_ha": round(self.carbon_p95, 2),
                "total_tc": round(self.total_carbon_t, 1),
            },
            "co2e": {
                "mean_tco2e_ha": round(self.co2e_mean, 2),
                "p05_tco2e_ha": round(self.co2e_p05, 2),
                "p95_tco2e_ha": round(self.co2e_p95, 2),
                "total_tco2e": round(self.total_co2e_t, 1),
            },
            "belowground": {
                "mean_tc_ha": round(self.belowground_carbon_mean, 2),
                "root_to_shoot": ROOT_TO_SHOOT,
                "note": (
                    "Belowground carbon is inferred from an IPCC default "
                    "root-to-shoot ratio, not observed. It is excluded from the "
                    "aboveground figures above."
                ),
            },
            "constants": {
                "carbon_fraction": CARBON_FRACTION,
                "carbon_fraction_source": "IPCC 2006 GL Vol.4 Ch.4 Table 4.3",
                "co2e_per_carbon": round(CO2E_PER_CARBON, 5),
                "co2e_source": "Molecular weight ratio CO2:C (44.01 / 12.011)",
            },
        }


def biomass_to_carbon(
    agb_mean: float,
    agb_p05: float,
    agb_p95: float,
    total_stock_mg: float,
    agb_grid: np.ndarray,
) -> CarbonResult:
    """Convert an AGB estimate and its interval into carbon and CO2e."""
    c_mean = agb_mean * CARBON_FRACTION
    c_p05 = agb_p05 * CARBON_FRACTION
    c_p95 = agb_p95 * CARBON_FRACTION

    total_c = total_stock_mg * CARBON_FRACTION  # 1 Mg dry matter -> t C

    return CarbonResult(
        carbon_mean=c_mean,
        carbon_p05=c_p05,
        carbon_p95=c_p95,
        co2e_mean=c_mean * CO2E_PER_CARBON,
        co2e_p05=c_p05 * CO2E_PER_CARBON,
        co2e_p95=c_p95 * CO2E_PER_CARBON,
        total_carbon_t=total_c,
        total_co2e_t=total_c * CO2E_PER_CARBON,
        carbon_grid=agb_grid * CARBON_FRACTION,
        belowground_carbon_mean=agb_mean * ROOT_TO_SHOOT * CARBON_FRACTION,
    )
