"""
src/experiment_logger.py

ExperimentLogger の公開エントリポイント。
実装は src/pipeline/logger.py に集約されている。
"""
from .pipeline.logger import ExperimentLogger, ResultRecord, record_result

__all__ = ["ExperimentLogger", "ResultRecord", "record_result"]