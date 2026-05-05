#!/usr/bin/env python3
"""Test script to verify the Sarathi implementation works."""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from engine import Engine, TaskContext, Phase

def test_basic_lifecycle():
    """Test running a task through the basic lifecycle."""
    print("Testing Sarathi implementation...")

    # Create engine
    engine = Engine()

    # Create a test task
    task = TaskContext(
        task_id=engine.generate_task_id("Implement user authentication"),
        description="Implement user authentication for the web app",
    )

    print(f"Generated Task ID: {task.task_id}")
    print(f"Task Description: {task.description}")
    print(f"Initial Complexity: {task.complexity.value}")

    # Run the task
    result = engine.run_task(task)

    print(f"\nTask completed with {len(result.phase_results)} phases executed")

    # Show results
    for pr in result.phase_results:
        print(f"  {pr.phase.value}: {pr.outcome}")
        if pr.evidence:
            key_evidences = [f"{k}={v}" for k, v in pr.evidence.items() if isinstance(v, (str, int, bool))][:3]
            print(f"    Evidence: {', '.join(key_evidences)}")

    # Test persistence
    print(f"\nTesting persistence...")
    saved_tasks = engine.persistence.list_tasks()
    print(f"Saved tasks: {saved_tasks}")

    if saved_tasks:
        loaded_task = engine.persistence.load_task(saved_tasks[0])
        if loaded_task:
            print(f"Successfully loaded task: {loaded_task.task_id}")
        else:
            print("Failed to load task")

    print("\n✓ Basic lifecycle test completed!")

if __name__ == "__main__":
    test_basic_lifecycle()