"""Command-line interface for testing AI search assistance and triggering iterative training."""

import argparse
import json
import sys
from ai_search.integration import AIOrchestratorBridge


def main():
    parser = argparse.ArgumentParser(description="NYS GIS AI Search & Iterative Trainer CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Search command
    search_parser = subparsers.add_parser("search", help="Perform AI-enhanced search analysis on a query.")
    search_parser.add_argument("query", type=str, help="Search query text (e.g., 'Route 44' or '44 8601').")

    # Feedback / Log command
    feedback_parser = subparsers.add_parser("feedback", help="Log a search interaction for training.")
    feedback_parser.add_argument("--query", type=str, required=True, help="Search query.")
    feedback_parser.add_argument("--type", type=str, default="suggestions", help="Result type.")
    feedback_parser.add_argument("--selected", type=str, help="Selected suggestion text.")

    # Train command
    train_parser = subparsers.add_parser("train", help="Trigger an iterative training cycle from collected feedback.")
    train_parser.add_argument("--batch-size", type=int, default=500, help="Maximum records to train on.")

    args = parser.parse_args()
    bridge = AIOrchestratorBridge()

    if args.command == "search":
        print(f"Analyzing query: '{args.query}'...")
        intent = bridge.model.classify_intent(args.query)
        entities = bridge.model.extract_entities(args.query)
        print("\n--- AI Model Analysis ---")
        print(f"Intent Scores : {json.dumps(intent, indent=2)}")
        print(f"Extracted     : {json.dumps(entities, indent=2)}")

        mock_suggestions = [{"text": f"Result for {args.query}"}, {"text": "Alternative NYS Location"}]
        reranked = bridge.enhance_search(args.query, mock_suggestions)
        print(f"Reranked Suggestions: {json.dumps(reranked, indent=2)}")

        bridge.record_feedback(args.query, "cli_search", {"text": args.query}, {"intent": intent})

    elif args.command == "feedback":
        selected_obj = {"text": args.selected} if args.selected else None
        bridge.record_feedback(args.query, args.type, selected_obj)
        print(f"Successfully recorded feedback for query: '{args.query}'")

    elif args.command == "train":
        print("Starting iterative training cycle...")
        result = bridge.trigger_training()
        print(f"Training Result: {json.dumps(result, indent=2)}")


if __name__ == "__main__":
    main()
