import os
from pathlib import Path

from pydantic import BaseModel


class Settings(BaseModel):
    data_dir: Path = Path(os.environ.get("MKT_DATA_DIR", "data"))
    cdp_url: str = os.environ.get("CDP_URL", "http://localhost:29229")
    openai_model: str = os.environ.get("MKT_CLASSIFIER_MODEL", "gpt-5.4")
    transcribe_model: str = os.environ.get("MKT_TRANSCRIBE_MODEL", "gpt-4o-mini-transcribe")
    video_model: str = os.environ.get("MKT_VIDEO_MODEL", "bytedance/seedance-2.0-fast")
    apify_token: str | None = os.environ.get("APIFY_TOKEN")

    @property
    def db_path(self) -> Path:
        return self.data_dir / "mkt.sqlite"

    @property
    def videos_dir(self) -> Path:
        return self.data_dir / "videos"

    @property
    def renders_dir(self) -> Path:
        return self.data_dir / "renders"


settings = Settings()
