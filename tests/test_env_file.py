from bot.core.env_file import read_env_values, update_env_file


def test_update_env_file_preserves_unrelated_values_and_removes_keys(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "TOKEN=secret",
                "OLD_KEY=value",
                "TRANSLATION_CACHE_SIZE=1000",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    update_env_file(
        env_path,
        {
            "TRANSLATION_CACHE_SIZE": "500",
            "WRITING_FEEDBACK_LLM_TIMEOUT_SECONDS": "8",
        },
        remove_keys={"OLD_KEY"},
    )

    values = read_env_values(env_path)

    assert values["TOKEN"] == "secret"
    assert values["TRANSLATION_CACHE_SIZE"] == "500"
    assert values["WRITING_FEEDBACK_LLM_TIMEOUT_SECONDS"] == "8"
    assert "OLD_KEY" not in values
