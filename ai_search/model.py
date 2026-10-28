"""Local NLP model for query intent classification, entity extraction, and semantic suggestion reranking using scikit-learn and sentence-transformers."""

import functools
import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple

import joblib
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline

logger = logging.getLogger(__name__)

# Try importing sentence_transformers; provide a lightweight fallback if unavailable
try:
    from sentence_transformers import SentenceTransformer, util
    HAS_SENTENCE_TRANSFORMERS = True
except Exception:
    HAS_SENTENCE_TRANSFORMERS = False


class AISearchModel:
    """Local NLP model assisting search resolution using scikit-learn and sentence embeddings."""

    def __init__(self, model_path: Optional[str] = None):
        self.model_path = model_path or os.path.join(
            os.path.expanduser("~"), ".gemini", "tmp", "gis-proj", "ai_intent_model.joblib"
        )
        self.trained_iterations = 0
        self.vectorizer = TfidfVectorizer(max_features=1000)
        self.classifier = LogisticRegression(max_iter=200)
        self.pipeline: Optional[Pipeline] = None
        
        # Initialize semantic encoder if available
        self.embedder = None
        if HAS_SENTENCE_TRANSFORMERS:
            try:
                self.embedder = SentenceTransformer("all-MiniLM-L6-v2")
            except Exception as e:
                logger.warning(f"Could not load SentenceTransformer model: {e}")

        # In-memory embedding cache to avoid redundant tensor encoding
        self._embedding_cache: Dict[str, Any] = {}

        self._load_model()
        self._ensure_default_classifier()

    def _ensure_default_classifier(self) -> None:
        """Ensures the intent classifier has baseline training data so it can classify immediately."""
        if self.pipeline is not None:
            return

        X_seed = [
            "42.5000, -73.7500", "12.34, -74.56", "38.8951, -77.0364",
            "marker 44 8601 1035", "ref marker 12", "marker 9W",
            "5700 Route 44 55", "123 Main Street Albany NY", "456 State St", "120 Washington Ave",
            "Route 44 & Route 299", "Main St at Broadway", "Broadway / 5th Ave",
            "Albany", "Ulster County", "Kerhonkson", "Catskill Mountains"
        ]
        y_seed = [
            "coordinate", "coordinate", "coordinate",
            "marker", "marker", "marker",
            "address", "address", "address", "address",
            "intersection", "intersection", "intersection",
            "place", "place", "place", "place"
        ]

        try:
            self.pipeline = Pipeline([
                ("tfidf", TfidfVectorizer()),
                ("clf", LogisticRegression(max_iter=200))
            ])
            self.pipeline.fit(X_seed, y_seed)
        except Exception as e:
            logger.error(f"Failed to initialize default intent classifier: {e}")

    def _load_model(self) -> None:
        if os.path.exists(self.model_path):
            try:
                data = joblib.load(self.model_path)
                self.pipeline = data.get("pipeline")
                self.trained_iterations = data.get("trained_iterations", 0)
                logger.info(f"Loaded trained AI intent model from {self.model_path}")
            except Exception as e:
                logger.error(f"Failed to load intent model: {e}")

    def save_model(self) -> None:
        try:
            os.makedirs(os.path.dirname(self.model_path), exist_ok=True)
            joblib.dump({
                "pipeline": self.pipeline,
                "trained_iterations": self.trained_iterations
            }, self.model_path)
            logger.info(f"Saved AI intent model to {self.model_path}")
        except Exception as e:
            logger.error(f"Failed to save intent model: {e}")

    def classify_intent(self, query: str) -> Dict[str, float]:
        """Classifies query intent using weighted blending of heuristic rules and scikit-learn ML probabilities."""
        query_clean = query.strip()
        scores = {
            "coordinate": 0.0,
            "marker": 0.0,
            "address": 0.0,
            "intersection": 0.0,
            "place": 0.1,
        }

        # Heuristic confidence scores
        heuristic_scores = scores.copy()
        if re.match(r"^-?\d+\.\d+[\s,]+-?\d+\.\d+$", query_clean):
            heuristic_scores["coordinate"] = 0.99
        if re.search(r"\b\d{2,4}\b", query_clean) and (
            "mile" in query_clean.lower() or re.search(r"\d+\s+\d+", query_clean)
        ):
            heuristic_scores["marker"] = 0.85
        if " & " in query_clean or " at " in query_clean.lower() or " / " in query_clean:
            heuristic_scores["intersection"] = 0.80
        if re.search(r"^\d+\s+[A-Za-z]+", query_clean):
            heuristic_scores["address"] = 0.80

        # ML classifier probabilities
        ml_scores = scores.copy()
        if self.pipeline is not None:
            try:
                classes = self.pipeline.classes_
                proba = self.pipeline.predict_proba([query_clean])[0]
                for cls_name, prob in zip(classes, proba):
                    if cls_name in ml_scores:
                        ml_scores[cls_name] = float(prob)
            except Exception as e:
                logger.debug(f"Classifier prediction error: {e}")

        # Weighted blending (0.7 ML probability + 0.3 heuristic weight for high-confidence rules)
        for k in scores:
            h_val = heuristic_scores[k]
            m_val = ml_scores[k]
            if h_val > 0.5:
                scores[k] = max(h_val, m_val)
            else:
                scores[k] = 0.7 * m_val + 0.3 * h_val

        return scores

    def extract_entities(self, query: str) -> Dict[str, Optional[str]]:
        """Extracts structured entities such as route numbers, counties, or markers."""
        entities: Dict[str, Optional[str]] = {
            "route": None,
            "marker_number": None,
            "location_hint": None,
        }

        route_match = re.search(r"\b(?:Route|Rt|NY|I)[\s-]?(\d+)\b", query, re.IGNORECASE)
        if route_match:
            entities["route"] = route_match.group(1)

        marker_match = re.search(r"\b(\d{2,4}\s+\d{3,4}(?:\s+\d{3,4})?)\b", query)
        if marker_match:
            entities["marker_number"] = marker_match.group(1)

        return entities

    def rerank_suggestions(self, query: str, suggestions: List[Dict]) -> List[Dict]:
        """Reranks suggestion candidates using sentence-transformers semantic similarity (with caching & batching) and entity boosts."""
        if not suggestions:
            return suggestions

        entities = self.extract_entities(query)
        scored = []

        # Get or cache query embedding
        query_embedding = None
        if self.embedder is not None:
            if query in self._embedding_cache:
                query_embedding = self._embedding_cache[query]
            else:
                try:
                    query_embedding = self.embedder.encode(query, convert_to_tensor=True)
                    if len(self._embedding_cache) > 500:
                        self._embedding_cache.pop(next(iter(self._embedding_cache)))
                    self._embedding_cache[query] = query_embedding
                except Exception as e:
                    logger.debug(f"Query embedding error: {e}")

        texts = [s.get("text", "") for s in suggestions]
        cos_scores = None
        if self.embedder is not None and query_embedding is not None and texts:
            try:
                # Batch encode suggestions with batch_size=32 for efficiency
                suggestion_embeddings = self.embedder.encode(
                    texts, batch_size=32, show_progress_bar=False, convert_to_tensor=True
                )
                cos_scores = util.cos_sim(query_embedding, suggestion_embeddings)[0]
            except Exception as e:
                logger.debug(f"Suggestion embedding similarity error: {e}")

        for idx, s in enumerate(suggestions):
            score = 1.0
            text = s.get("text", "").lower()

            if query_embedding is not None and cos_scores is not None:
                score += float(cos_scores[idx]) * 2.0

            if entities.get("location_hint") and entities["location_hint"] in text:
                score += 0.5

            scored.append((score, s))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [s for _, s in scored]

    def export_to_onnx(self, onnx_path: str = "ai_intent_model.onnx") -> str:
        """Exports the trained scikit-learn intent classifier pipeline to ONNX format."""
        if self.pipeline is None:
            raise ValueError("No trained pipeline available for ONNX export.")
        try:
            from skl2onnx import convert_sklearn
            from skl2onnx.common.data_types import StringTensorType

            initial_type = [("input_string", StringTensorType([None, 1]))]
            onnx_model = convert_sklearn(self.pipeline, initial_types=initial_type)
            
            os.makedirs(os.path.dirname(os.path.abspath(onnx_path)), exist_ok=True)
            with open(onnx_path, "wb") as f:
                f.write(onnx_model.SerializeToString())
            logger.info(f"Successfully exported intent model to ONNX: {onnx_path}")
            return onnx_path
        except Exception as e:
            logger.error(f"Failed to export model to ONNX: {e}")
            raise

    def update_model(self, training_data: List[Dict]) -> int:
        """Trains/updates the scikit-learn intent classifier using logged search interactions."""
        X = []
        y = []

        for record in training_data:
            q = record.get("query")
            res_type = record.get("result_type")
            if q and res_type in ["coordinate", "marker", "address", "intersection", "place"]:
                X.append(q)
                y.append(res_type)

        if len(X) >= 2:
            try:
                self.pipeline = Pipeline([
                    ("tfidf", TfidfVectorizer()),
                    ("clf", LogisticRegression(max_iter=200))
                ])
                self.pipeline.fit(X, y)
                logger.info(f"Trained intent classifier on {len(X)} samples.")
            except Exception as e:
                logger.error(f"Failed to fit intent classifier: {e}")

        self.trained_iterations += len(training_data)
        self.save_model()
        logger.info(f"AI model updated. Total iterations: {self.trained_iterations}")
        return self.trained_iterations
