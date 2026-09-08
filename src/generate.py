"""Точка входа для детерминированной генерации."""

from src.config import load_params
from src.model import generate, load_model, set_seed


def main() -> None:
    params = load_params()
    set_seed(int(params["generate"]["seed"]))

    tokenizer, model = load_model(params)
    print(f"Модель: {params['model']['name']}")

    text, n_tokens = generate(
        tokenizer,
        model,
        params,
        params["bench"]["prompt"],
    )

    print(text)
    print(f"\n[{n_tokens} токенов]")


if __name__ == "__main__":
    main()
