"""Unit tests for the ai_search package."""

import os
import tempfile
import unittest

from ai_search import AIOrchestratorBridge, AISearchModel, SearchDataCollector, IterativeTrainer


class TestAISearchPackage(unittest.TestCase):
    """Test suite for AI search model, collector, trainer, and bridge."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_training.jsonl")
        self.bridge = AIOrchestratorBridge(storage_path=self.db_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_intent_classification(self):
        model = AISearchModel()
        
        coord_intent = model.classify_intent("42.6526, -73.7562")
        self.assertGreater(coord_intent["coordinate"], 0.9)

        marker_intent = model.classify_intent("44 8601 1035")
        self.assertGreater(marker_intent["marker"], 0.8)

        address_intent = model.classify_intent("120 Washington Ave")
        self.assertGreater(address_intent["address"], 0.7)

    def test_entity_extraction(self):
        model = AISearchModel()
        entities = model.extract_entities("Route 9 Albany")
        self.assertEqual(entities["route"], "9")

        marker_entities = model.extract_entities("Marker 44 8601")
        self.assertEqual(marker_entities["marker_number"], "44 8601")

    def test_collector_and_trainer(self):
        collector = SearchDataCollector(storage_path=self.db_path)
        collector.log_interaction("Albany", "suggestions", {"text": "Albany, NY"}, {"count": 5})

        dataset = collector.load_dataset()
        self.assertEqual(len(dataset), 1)
        self.assertEqual(dataset[0]["query"], "Albany")

        trainer = IterativeTrainer(AISearchModel(), collector)
        result = trainer.train_iteration()
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["samples_trained"], 1)

    def test_bridge_integration(self):
        suggestions = [{"text": "Main St, Albany"}, {"text": "Broadway, Albany"}]
        reranked = self.bridge.enhance_search("Broadway", suggestions)
        self.assertEqual(len(reranked), 2)

        self.bridge.record_feedback("Broadway", "suggestions", suggestions[1], {"clicked": True})
        training_result = self.bridge.trigger_training()
        self.assertEqual(training_result["status"], "success")


if __name__ == "__main__":
    unittest.main()
