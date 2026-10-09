"""Diesel (軽油) CO2 emission factor for engine-bus operation, with its derivation.

Source: 環境省「温室効果ガス排出量 算定・報告・公表制度」
算定方法・排出係数一覧（R5年度実績以降の排出量算定用、令和6年度報告から適用）
https://policies.env.go.jp/earth/ghg-santeikohyo/calc.html
PDF: https://policies.env.go.jp/earth/ghg-santeikohyo/files/calc/itiran_2023_rev4.pdf

  軽油 単位発熱量      38.0   GJ/kL
  軽油 炭素排出係数    0.0188 tC/GJ
  CO2/C 分子量比       44/12

  38.0 GJ/kL * 0.0188 tC/GJ * 44/12 = 2.6195 t-CO2/kL = 2.62 kg-CO2/L (3 significant digits)

Scope: tank-to-wheel combustion CO2 (Scope 1), the same boundary as the
statutory report.  Upstream fuel production (well-to-tank) and CH4/N2O are not
included, so the comparison with grid electricity must use a generation-side
(Scope 2) electricity factor.  The previous model mixed 2.58 (pre-revision
factor, 37.7 GJ/kL * 0.0187 tC/GJ), 2.585895 (catalog g/km / km/L) and 2.64/2.67
(unsourced); this module replaces those defaults.
"""
from __future__ import annotations

DIESEL_HEAT_VALUE_GJ_PER_KL = 38.0
DIESEL_CARBON_FACTOR_TC_PER_GJ = 0.0188
CO2_PER_CARBON_MASS_RATIO = 44.0 / 12.0
DIESEL_CO2_KG_PER_L_EXACT = (
    DIESEL_HEAT_VALUE_GJ_PER_KL * DIESEL_CARBON_FACTOR_TC_PER_GJ * CO2_PER_CARBON_MASS_RATIO
)
# The statutory table publishes the product rounded to 2.62 t-CO2/kL.
DIESEL_CO2_KG_PER_L = 2.62

DIESEL_CO2_SOURCE = {
    'factor_kg_co2_per_l': DIESEL_CO2_KG_PER_L,
    'exact_product_kg_co2_per_l': DIESEL_CO2_KG_PER_L_EXACT,
    'heat_value_gj_per_kl': DIESEL_HEAT_VALUE_GJ_PER_KL,
    'carbon_factor_tc_per_gj': DIESEL_CARBON_FACTOR_TC_PER_GJ,
    'co2_per_carbon': '44/12',
    'boundary': 'tank_to_wheel_combustion_co2_scope1',
    'excluded': ['well_to_tank_upstream', 'CH4', 'N2O'],
    'publisher': '環境省 温室効果ガス排出量 算定・報告・公表制度',
    'table': '算定方法・排出係数一覧（R5年度実績以降の排出量算定用）',
    'url': 'https://policies.env.go.jp/earth/ghg-santeikohyo/files/calc/itiran_2023_rev4.pdf',
    'previous_factor_kg_co2_per_l': 2.58,
    'previous_factor_derivation': '37.7 GJ/kL * 0.0187 tC/GJ * 44/12 (R4年度実績まで)',
}


def diesel_co2_g_per_km(fuel_efficiency_km_per_l: float) -> float:
    """Operation CO2 per km for a diesel bus at a stated fuel efficiency."""
    value = float(fuel_efficiency_km_per_l)
    if not value > 0.0:
        raise ValueError('fuel_efficiency_km_per_l must be positive')
    return DIESEL_CO2_KG_PER_L * 1000.0 / value
