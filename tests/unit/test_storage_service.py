from backend.storage_service import StorageService


def test_list_conversations_includes_cost_and_squad_fingerprint(tmp_path):
    storage = StorageService(data_dir=str(tmp_path / "conversations"))
    conversation = storage.create_conversation("conv-1", mode="council")
    conversation["messages"] = [
        {"role": "user", "content": "question"},
        {
            "role": "assistant",
            "stage1": [],
            "stage2": [],
            "stage3": {"model": "chair/model", "response": "answer"},
            "metadata": {
                "arena_models": ["vendor/z", "vendor/a"],
                "chairman_model": "chair/model",
                "cost": {"turn_cost_usd": 0.125, "total_tokens": 321, "calls": 3},
            },
        },
    ]
    storage.save_conversation(conversation)

    [summary] = storage.list_conversations()

    assert summary["total_cost_usd"] == 0.125
    assert summary["total_tokens"] == 321
    assert summary["arena_models"] == ["vendor/z", "vendor/a"]
    assert summary["chairman_model"] == "chair/model"
    assert summary["squad_fingerprint"] == "chair/model::vendor/a|vendor/z"
