"""Download the depth model into data/models/ once, so the app runs offline afterwards."""

from huggingface_hub import snapshot_download

from depthwizard.config import load_config, resolve_path


def main() -> None:
    cfg = load_config()
    dest = resolve_path(cfg.model.local_dir)
    snapshot_download(
        repo_id=cfg.model.id,
        local_dir=dest,
        allow_patterns=["*.json", "*.safetensors", "README.md", "LICENSE*"],
    )
    print(dest)


if __name__ == "__main__":
    main()
