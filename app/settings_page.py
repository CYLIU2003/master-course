"""
app/settings_page.py

Composable Settings tab layout.
"""

from __future__ import annotations

import streamlit as st

from app.system_config_editor import render_system_config_editor


def render_settings_tab(config_mode: str, data_dir: str = "data") -> None:
    st.markdown(
        """
    <div class="info-box">
      <div class="info-icon">🧭</div>
      <div>
        <strong>推奨ワークフロー:</strong>
        1) 路線・時刻表設定 → 2) 車両設定 → 3) 営業所設定 → 4) システム設定・適用
      </div>
    </div>
    """,
        unsafe_allow_html=True,
    )

    (
        settings_tab_route,
        settings_tab_vehicle,
        settings_tab_depot,
        settings_tab_system,
    ) = st.tabs(
        [
            "🗺️ 路線・時刻表",
            "🚌 車両フリート",
            "🏢 営業所・配車",
            "⚙️ システム設定・適用",
        ]
    )

    with settings_tab_route:
        try:
            from app.route_profile_editor import render_route_profile_editor

            render_route_profile_editor(data_dir=data_dir)
        except ImportError:
            st.error(
                "地図モードを使う場合は以下をインストールしてください:\n"
                "```\npip install folium streamlit-folium\n```"
            )
        except Exception as exc:
            st.error(f"路線管理エディタの読み込みに失敗しました: {exc}")
            st.exception(exc)

    with settings_tab_vehicle:
        if config_mode == "JSON インポート" and st.session_state.config is not None:
            st.info(
                "JSON モードでは車両編集結果は即時反映されません。手動設定モードで適用してください。"
            )
        from app.vehicle_fleet_editor import render_vehicle_fleet_editor

        render_vehicle_fleet_editor()

    with settings_tab_depot:
        try:
            from app.depot_profile_editor import render_depot_profile_editor

            render_depot_profile_editor(data_dir=data_dir, show_energy_settings=False)
        except Exception as exc:
            st.error(f"営業所管理エディタの読み込みに失敗しました: {exc}")

    with settings_tab_system:
        render_system_config_editor(config_mode=config_mode, data_dir=data_dir)
