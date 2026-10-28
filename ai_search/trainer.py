"""Iterative training orchestrator for updating the local NLP search model."""

import logging
from typing import Dict, List, Optional
from ai_search.collector import SearchDataCollector
from ai_search.model import AISearchModel

logger = logging.getLogger(__name__)


class IterativeTrainer:
    """Manages iterative model training based on collected frontend search data."""

    def __init__(self, model: AISearchModel, collector: SearchDataCollector):
        self.model = model
        self.collector = collector

    def train_iteration(self, batch_size: int = 500) -> Dict:
        """Performs a single iterative training step using recent search logs."""
        dataset = self.collector.load_dataset(max_records=batch_size)
        if not dataset:
            logger.info("No training data available for this iteration.")
            return {"status": "skipped", "samples_trained": 0, "total_iterations": self.model.trained_iterations}

        iterations = self.model.update_model(dataset)
        return {
            "status": "success",
            "samples_trained": len(dataset),
            "total_iterations": iterations,
        }
