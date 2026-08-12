import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    ro_mysql_host: str
    ro_mysql_port: int
    ro_mysql_user: str
    ro_mysql_password: str
    ro_mysql_database: str
    skybear_uat_url: str
    skybear_prod_url: str
    webuytravel_url: str


def load_settings() -> Settings:
    load_dotenv()

    required = [
        "SKYBEAR_RO_MYSQL_HOST",
        "SKYBEAR_RO_MYSQL_USER",
        "SKYBEAR_RO_MYSQL_PASSWORD",
        "SKYBEAR_RO_MYSQL_DATABASE",
    ]
    missing = [k for k in required if not os.getenv(k)]
    if missing:
        raise RuntimeError(f"Missing env vars: {', '.join(missing)}")

    return Settings(
        ro_mysql_host=os.environ["SKYBEAR_RO_MYSQL_HOST"],
        ro_mysql_port=int(os.getenv("SKYBEAR_RO_MYSQL_PORT", "3306")),
        ro_mysql_user=os.environ["SKYBEAR_RO_MYSQL_USER"],
        ro_mysql_password=os.environ["SKYBEAR_RO_MYSQL_PASSWORD"],
        ro_mysql_database=os.environ["SKYBEAR_RO_MYSQL_DATABASE"],
        skybear_uat_url=os.getenv("SKYBEAR_UAT_URL", "https://test01.travel.webuy.ren"),
        skybear_prod_url=os.getenv("SKYBEAR_PROD_URL", "https://travel.webuysg.com"),
        webuytravel_url=os.getenv("WEBUYTRAVEL_URL", "https://www.webuytravel.sg"),
    )
