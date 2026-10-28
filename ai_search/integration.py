"""Integration bridge between GIS PipelineOrchestrator and AI search capabilities."""

import logging
from typing import Dict, List, Optional
from ai_search.collector import SearchDataCollector
from ai_search.model import AISearchModel
from ai_search.trainer import IterativeTrainer

logger = logging.getLogger(__name__)


class AIOrchestratorBridge:
    """Enhances GIS pipeline search operations with local AI model predictions and logging."""

    def __init__(self, storage_path: Optional[str] = None):
        self.model = AISearchModel()
        self.collector = SearchDataCollector(storage_path=storage_path)
        self.trainer = IterativeTrainer(self.model, self.collector)

    def enhance_search(self, query: str, raw_suggestions: List[Dict]) -> List[Dict]:
        """Classifies intent, extracts entities, and reranks suggestions using the AI model."""
        intent = self.model.classify_intent(query)
        entities = self.model.extract_entities(query)
        logger.info(f"AI Intent for '{query}': {intent} | Entities: {entities}")
        
        reranked = self.model.rerank_suggestions(query, raw_suggestions)
        return reranked

    def record_feedback(
        self,
        query: str,
        result_type: str,
        selected_suggestion: Optional[Dict] = None,
        gis_metadata: Optional[Dict] = None,
    ) -> None:
        """Records user search feedback for iterative learning."""
        self.collector.log_interaction(
            query=query,
            result_type=result_type,
            selected_suggestion=selected_suggestion,
            gis_metadata=gis_metadata,
        )

    def trigger_training(self) -> Dict:
        """Triggers an iterative training iteration."""
        return self.trainer.train_iteration()
